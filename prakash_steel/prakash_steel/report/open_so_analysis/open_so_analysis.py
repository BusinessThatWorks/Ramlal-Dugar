import copy
import math
from collections import OrderedDict

import frappe
from frappe import _, qb
from frappe.query_builder import CustomFunction
from frappe.query_builder.functions import Max
from frappe.utils import date_diff, flt, getdate


def execute(filters=None):
	if not filters:
		return [], [], None, []

	validate_filters(filters)

	columns = get_columns(filters)
	conditions = get_conditions(filters)
	data = get_data(conditions, filters)
	so_elapsed_time = get_so_elapsed_time(data)

	if not data:
		return [], [], None, []

	data, chart_data = prepare_data(data, so_elapsed_time, filters)

	return columns, data, None, chart_data


def validate_filters(filters):
	from_date, to_date = filters.get("from_date"), filters.get("to_date")

	if not from_date and to_date:
		frappe.throw(_("From and To Dates are required."))
	elif date_diff(to_date, from_date) < 0:
		frappe.throw(_("To Date cannot be before From Date."))


def get_conditions(filters):
	conditions = ""
	if filters.get("from_date") and filters.get("to_date"):
		conditions += " and so.transaction_date between %(from_date)s and %(to_date)s"

	if filters.get("company"):
		conditions += " and so.company = %(company)s"

	if filters.get("sales_order"):
		conditions += " and so.name in %(sales_order)s"

	if filters.get("status"):
		conditions += " and so.status in %(status)s"

	if filters.get("warehouse"):
		conditions += " and soi.warehouse = %(warehouse)s"

	return conditions


def get_data(conditions, filters):
	# Fetch buffer_flag and item_type from Item, then calculate sku_type in Python
	data = frappe.db.sql(
		f"""
        SELECT
            so.transaction_date as date,
            soi.delivery_date as delivery_date,
            so.name as sales_order,
            so.status,
            so.customer,
            soi.item_code,
            i.custom_buffer_flag as buffer_flag,
            i.custom_item_type as item_type,
            DATEDIFF(CURRENT_DATE, soi.delivery_date) as delay_days,
            IF(so.status in ('Completed','To Bill'), 0, (SELECT delay_days)) as delay,
            soi.qty,
            soi.rate,
            soi.delivered_qty,
            (soi.qty - soi.delivered_qty) AS pending_qty,
            IFNULL(SUM(sii.qty), 0) as billed_qty,
            soi.base_amount as amount,
            (soi.delivered_qty * soi.base_rate) as delivered_qty_amount,
            (soi.billed_amt * IFNULL(so.conversion_rate, 1)) as billed_amount,
            (soi.base_amount - (soi.billed_amt * IFNULL(so.conversion_rate, 1))) as pending_amount,
            soi.warehouse as warehouse,
            so.company,
            so.currency,
            soi.name,
            soi.description as description
        FROM
            `tabSales Order` so,
            `tabSales Order Item` soi
        LEFT JOIN `tabItem` i ON i.name = soi.item_code
        LEFT JOIN `tabSales Invoice Item` sii
            ON sii.so_detail = soi.name and sii.docstatus = 1
        WHERE
            soi.parent = so.name
            and so.status not in ('Stopped', 'On Hold')
            and so.docstatus = 1
            {conditions}
        GROUP BY soi.name
        ORDER BY
            soi.delivery_date ASC,
            so.name,
            soi.item_code
    """,
		filters,
		as_dict=1,
	)

	return data


def get_so_elapsed_time(data):
	"""
	query SO's elapsed time till latest delivery note
	"""
	so_elapsed_time = OrderedDict()
	if data:
		sales_orders = [x.sales_order for x in data]

		so = qb.DocType("Sales Order")
		soi = qb.DocType("Sales Order Item")
		dn = qb.DocType("Delivery Note")
		dni = qb.DocType("Delivery Note Item")

		to_seconds = CustomFunction("TO_SECONDS", ["date"])

		query = (
			qb.from_(so)
			.inner_join(soi)
			.on(soi.parent == so.name)
			.left_join(dni)
			.on(dni.so_detail == soi.name)
			.left_join(dn)
			.on(dni.parent == dn.name)
			.select(
				so.name.as_("sales_order"),
				soi.item_code.as_("so_item_code"),
				(to_seconds(Max(dn.posting_date)) - to_seconds(so.transaction_date)).as_("elapsed_seconds"),
			)
			.where((so.name.isin(sales_orders)) & (dn.docstatus == 1))
			.orderby(so.name, soi.name)
			.groupby(soi.name)
		)
		dn_elapsed_time = query.run(as_dict=True)

		for e in dn_elapsed_time:
			key = (e.sales_order, e.so_item_code)
			so_elapsed_time[key] = e.elapsed_seconds

	return so_elapsed_time


def calculate_sku_type(buffer_flag, item_type):
	"""Calculate SKU type based on buffer flag and item type
	Same mapping logic as calculate_sku_type in item.js
	buffer_flag: 'Buffer' or 'Non-Buffer'
	item_type: 'FG', 'INT', 'RM'
	"""
	if not item_type:
		return None

	is_buffer = buffer_flag == "Buffer"

	if item_type == "FG":
		return "FGMTA" if is_buffer else "FGMTO"
	elif item_type == "INT":
		return "SFGMTA" if is_buffer else "SFGMTO"
	elif item_type == "RAW":
		return "PTA" if is_buffer else "PTO"

	return None


def prepare_data(data, so_elapsed_time, filters):
	completed, pending = 0, 0

	# Filter out rows where pending_qty (qty_to_deliver) is 0 or negative
	# Only show items that still need to be delivered (Open SO items)
	# Also filter out rows where sales order status is "Closed" or "Cancelled"
	data = [
		row
		for row in data
		if flt(row.get("pending_qty") or 0) > 0 and row.get("status") not in ["Closed", "Cancelled"]
	]

	# Build stock map: total actual_qty across all warehouses for each item
	item_codes = {row.get("item_code") for row in data if row.get("item_code")}
	stock_map = {}
	if item_codes:
		bin_rows = frappe.db.sql(
			"""
            SELECT item_code, SUM(actual_qty) as stock
            FROM `tabBin`
            WHERE item_code in %(items)s
            GROUP BY item_code
            """,
			{"items": tuple(item_codes)},
			as_dict=True,
		)
		stock_map = {d.item_code: flt(d.stock) for d in bin_rows}

	# Remaining stock per item for FIFO allocation (start from total stock)
	remaining_stock = dict(stock_map)

	if filters.get("group_by_so"):
		sales_order_map = {}

	for row in data:
		# sum data for chart
		completed += row["billed_amount"]
		pending += row["pending_amount"]

		# Convert quantity fields to integers
		row["qty"] = int(flt(row.get("qty", 0)))
		row["delivered_qty"] = int(flt(row.get("delivered_qty", 0)))
		row["pending_qty"] = int(flt(row.get("pending_qty", 0)))
		row["billed_qty"] = int(flt(row.get("billed_qty", 0)))

		# prepare data for report view
		row["qty_to_bill"] = int(flt(row["qty"]) - flt(row["billed_qty"]))
		row["delay"] = 0 if row["delay"] and row["delay"] < 0 else row["delay"]

		# calculate SKU Type using same rule as item.js
		buffer_flag = row.get("buffer_flag") or "Non-Buffer"
		item_type = row.get("item_type")
		row["sku_type"] = calculate_sku_type(buffer_flag, item_type)

		# expose item_type as visible column
		row["item_type"] = item_type

		# total stock across all warehouses for this item (for display)
		row["stock"] = int(flt(stock_map.get(row.get("item_code"), 0)))

		# Calculate remaining_days: negative of delay_days
		delay_days = row.get("delay_days")
		if delay_days is not None:
			row["remaining_days"] = -flt(delay_days)
		else:
			row["remaining_days"] = None

		# Calculate lead time: delivery_date - transaction_date (in days)
		if row.get("delivery_date") and row.get("date"):
			row["lead_time"] = date_diff(row["delivery_date"], row["date"])
		else:
			row["lead_time"] = None

		# Buffer Status = (remaining_days / lead_time) * 100
		remaining_days = row.get("remaining_days")
		lead_time = row.get("lead_time")
		buffer_status = None

		if remaining_days is not None:
			# Special case: if remaining_days is 0, buffer_status = 0% and order_status = RED
			if flt(remaining_days) == 0:
				buffer_status = 0
			elif lead_time:
				buffer_status = (flt(remaining_days) / flt(lead_time)) * 100
			else:
				buffer_status = flt(remaining_days) * 100

		numeric_status = None
		if buffer_status is not None:
			numeric_status = math.ceil(buffer_status)

		# Derive Order Status from numeric buffer status
		if numeric_status is None:
			row["order_status"] = None
		elif numeric_status < 0:
			row["order_status"] = "BLACK"
		elif numeric_status == 0:
			# Special case: remaining_days = 0 → buffer_status = 0% → order_status = RED
			row["order_status"] = "RED"
		elif 1 <= numeric_status <= 34:
			row["order_status"] = "RED"
		elif 35 <= numeric_status <= 67:
			row["order_status"] = "YELLOW"
		elif 68 <= numeric_status <= 100:
			row["order_status"] = "GREEN"
		else:  # > 100
			row["order_status"] = "WHITE"

		# Round up and show Buffer Status with % sign
		if numeric_status is not None:
			row["buffer_status"] = f"{int(numeric_status)}%"
		else:
			row["buffer_status"] = None

		# FIFO Stock Allocation and Shortage per item
		# Use pending_qty (qty_to_deliver) instead of order qty
		item_code = row.get("item_code")
		required_qty = flt(row.get("pending_qty") or 0)  # qty_to_deliver
		available_qty = flt(remaining_stock.get(item_code, 0))

		allocated = min(required_qty, available_qty)
		shortage = required_qty - allocated

		row["stock_allocation"] = int(allocated)
		row["shortage"] = int(shortage)

		# Calculate Line Fullkit for this line/item
		# If shortage = 0 → "Full-kit"
		# Else if stock_allocation = 0 → "Pending"
		# Else → "Partial"
		if flt(shortage) == 0:
			row["line_fullkit"] = "Full-kit"
		elif flt(allocated) == 0:
			row["line_fullkit"] = "Pending"
		else:
			row["line_fullkit"] = "Partial"

		# Reduce remaining stock for this item
		remaining_stock[item_code] = available_qty - allocated

		row["time_taken_to_deliver"] = (
			so_elapsed_time.get((row.sales_order, row.item_code))
			if row["status"] in ("To Bill", "Completed")
			else 0
		)

		if filters.get("group_by_so"):
			so_name = row["sales_order"]

			if so_name not in sales_order_map:
				# create an entry
				row_copy = copy.deepcopy(row)
				sales_order_map[so_name] = row_copy
			else:
				# update existing entry
				so_row = sales_order_map[so_name]
				so_row["required_date"] = max(getdate(so_row["delivery_date"]), getdate(row["delivery_date"]))
				so_row["delay"] = (
					min(so_row["delay"], row["delay"])
					if row["delay"] and so_row["delay"]
					else so_row["delay"]
				)

				# sum numeric columns
				fields = [
					"qty",
					"delivered_qty",
					"pending_qty",
					"billed_qty",
					"qty_to_bill",
					"amount",
					"delivered_qty_amount",
					"billed_amount",
					"pending_amount",
				]
				for field in fields:
					so_row[field] = flt(row[field]) + flt(so_row[field])

				# Convert quantity fields to integers after summing
				int_fields = ["qty", "delivered_qty", "pending_qty", "billed_qty", "qty_to_bill"]
				for field in int_fields:
					so_row[field] = int(flt(so_row[field]))

	# Calculate Order Fullkit: Group by sales_order and check line_fullkit values
	# Build a map of sales_order -> list of line_fullkit values
	so_line_fullkit_map = {}
	for row in data:
		so_name = row.get("sales_order")
		if so_name:
			if so_name not in so_line_fullkit_map:
				so_line_fullkit_map[so_name] = []
			line_fullkit_val = row.get("line_fullkit") or ""
			so_line_fullkit_map[so_name].append(line_fullkit_val)

	# For each sales order, determine Order Fullkit based on all line_fullkit values
	so_fullkit_map = {}
	for so_name, line_fullkits in so_line_fullkit_map.items():
		# Remove empty values
		line_fullkits = [lf for lf in line_fullkits if lf]

		if not line_fullkits:
			so_fullkit_map[so_name] = "Pending"
		elif all(lf == "Full-kit" for lf in line_fullkits):
			# All items are Full-kit
			so_fullkit_map[so_name] = "Full-kit"
		elif all(lf == "Pending" for lf in line_fullkits):
			# All items are Pending
			so_fullkit_map[so_name] = "Pending"
		else:
			# Mixed: any combination of Full-kit with Pending/Partial, or any Partial
			so_fullkit_map[so_name] = "Partial"

	# Assign Order Fullkit to each row based on its sales_order
	for row in data:
		so_name = row.get("sales_order")
		row["order_fullkit"] = so_fullkit_map.get(so_name, "Pending")

	chart_data = prepare_chart_data(pending, completed)

	if filters.get("group_by_so"):
		data = []
		for so in sales_order_map:
			data.append(sales_order_map[so])
		return data, chart_data

	return data, chart_data


def prepare_chart_data(pending, completed):
	labels = [_("Amount to Bill"), _("Billed Amount")]

	return {
		"data": {"labels": labels, "datasets": [{"values": [pending, completed]}]},
		"type": "donut",
		"height": 300,
	}


def get_columns(filters):
	columns = [
		{"label": _("Sales Order Date"), "fieldname": "date", "fieldtype": "Date", "width": 90},
		{
			"label": _("Sales Order"),
			"fieldname": "sales_order",
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 160,
		},
		{
			"label": _("Delivery Date"),
			"fieldname": "delivery_date",
			"fieldtype": "Date",
			"width": 120,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 130},
		{
			"label": _("Customer Name"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 130,
		},
		{
			"label": _("Item Type"),
			"fieldname": "item_type",
			"fieldtype": "Data",
			"width": 90,
		},
		{
			"label": _("SKU Type"),
			"fieldname": "sku_type",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Order Status"),
			"fieldname": "order_status",
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"label": _("Remaining Days"),
			"fieldname": "remaining_days",
			"fieldtype": "Int",
			"width": 110,
		},
		{
			"label": _("Lead Time"),
			"fieldname": "lead_time",
			"fieldtype": "Int",
			"width": 90,
		},
		{
			"label": _("Buffer Status (%)"),
			"fieldname": "buffer_status",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Stock"),
			"fieldname": "stock",
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"label": _("Stock Allocation"),
			"fieldname": "stock_allocation",
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"label": _("Shortage"),
			"fieldname": "shortage",
			"fieldtype": "Int",
			"width": 100,
		},
	]

	if not filters.get("group_by_so"):
		columns.append(
			{
				"label": _("Item Code"),
				"fieldname": "item_code",
				"fieldtype": "Link",
				"options": "Item",
				"width": 100,
			}
		)
		columns.append(
			{
				"label": _("Description"),
				"fieldname": "description",
				"fieldtype": "Small Text",
				"width": 100,
			}
		)

	columns.extend(
		[
			{
				"label": _("Order Qty"),
				"fieldname": "qty",
				"fieldtype": "Int",
				"width": 120,
				"convertible": "qty",
			},
			{
				"label": _("Rate"),
				"fieldname": "rate",
				"fieldtype": "Currency",
				"width": 120,
				"options": "currency",
				"convertible": "rate",
			},
			{
				"label": _("Delivered Qty"),
				"fieldname": "delivered_qty",
				"fieldtype": "Int",
				"width": 120,
				"convertible": "qty",
			},
			{
				"label": _("Qty to Deliver"),
				"fieldname": "pending_qty",
				"fieldtype": "Int",
				"width": 120,
				"convertible": "qty",
			},
			{
				"label": _("Billed Qty"),
				"fieldname": "billed_qty",
				"fieldtype": "Int",
				"width": 80,
				"convertible": "qty",
			},
			{
				"label": _("Qty to Bill"),
				"fieldname": "qty_to_bill",
				"fieldtype": "Int",
				"width": 80,
				"convertible": "qty",
			},
			{
				"label": _("Amount"),
				"fieldname": "amount",
				"fieldtype": "Currency",
				"width": 110,
				"options": "Company:company:default_currency",
				"convertible": "rate",
			},
			{
				"label": _("Billed Amount"),
				"fieldname": "billed_amount",
				"fieldtype": "Currency",
				"width": 110,
				"options": "Company:company:default_currency",
				"convertible": "rate",
			},
			{
				"label": _("Pending Amount"),
				"fieldname": "pending_amount",
				"fieldtype": "Currency",
				"width": 130,
				"options": "Company:company:default_currency",
				"convertible": "rate",
			},
			{
				"label": _("Amount Delivered"),
				"fieldname": "delivered_qty_amount",
				"fieldtype": "Currency",
				"width": 100,
				"options": "Company:company:default_currency",
				"convertible": "rate",
			},
			{
				"label": _("Delivery Date"),
				"fieldname": "delivery_date",
				"fieldtype": "Date",
				"width": 120,
			},
			{
				"label": _("Delay (in Days)"),
				"fieldname": "delay",
				"fieldtype": "Data",
				"width": 100,
			},
			{
				"label": _("Time Taken to Deliver"),
				"fieldname": "time_taken_to_deliver",
				"fieldtype": "Duration",
				"width": 100,
			},
		]
	)
	if not filters.get("group_by_so"):
		columns.append(
			{
				"label": _("Warehouse"),
				"fieldname": "warehouse",
				"fieldtype": "Link",
				"options": "Warehouse",
				"width": 100,
			}
		)
	columns.append(
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 100,
		}
	)

	# Add Line Fullkit and Order Fullkit columns at the end
	columns.append(
		{
			"label": _("Line Fullkit"),
			"fieldname": "line_fullkit",
			"fieldtype": "Data",
			"width": 120,
		}
	)
	columns.append(
		{
			"label": _("Order Fullkit"),
			"fieldname": "order_fullkit",
			"fieldtype": "Data",
			"width": 120,
		}
	)

	return columns

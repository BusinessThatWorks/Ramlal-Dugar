# Copyright (c) 2026, beetashoke chakraborty and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, today


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


def get_qualified_demand_map(filters):
	"""Get qualified demand map for all items"""
	today_date = today()

	so_rows = frappe.db.sql(
		"""
		SELECT
			soi.item_code,
			SUM(soi.qty - IFNULL(soi.delivered_qty, 0)) as so_qty
		FROM
			`tabSales Order` so
		INNER JOIN
			`tabSales Order Item` soi ON soi.parent = so.name
		WHERE
			so.status NOT IN ('Stopped', 'On Hold', 'Closed', 'Cancelled', 'Completed')
			AND so.docstatus = 1
			AND IFNULL(soi.delivery_date, '1900-01-01') <= %s
		GROUP BY
			soi.item_code
		""",
		(today_date,),
		as_dict=True,
	)

	return {d.item_code: flt(d.so_qty) for d in so_rows}


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	"""Define report columns"""
	return [
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 120,
		},
		{
			"label": _("SKU Type"),
			"fieldname": "sku_type",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Item Type"),
			"fieldname": "item_type",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Item Group"),
			"fieldname": "item_group",
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 120,
		},
		{
			"label": _("Category Name"),
			"fieldname": "category_name",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Buffer Flag"),
			"fieldname": "buffer_flag",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Store Stock"),
			"fieldname": "store_stock",
			"fieldtype": "Float",
			"width": 120,
		},
		{
			"label": _("Free Stock"),
			"fieldname": "free_stock",
			"fieldtype": "Float",
			"width": 120,
		},
	]


def get_data(filters=None):
	"""Get data for the report"""
	if not filters:
		filters = {}

	# Build WHERE conditions based on filters
	conditions = ["i.disabled = 0"]
	params = []

	# Item Code filter
	if filters.get("item_code"):
		conditions.append("i.name = %s")
		params.append(filters.get("item_code"))

	# Item Group filter
	if filters.get("item_group"):
		conditions.append("i.item_group = %s")
		params.append(filters.get("item_group"))

	# Category Name filter
	if filters.get("category_name"):
		conditions.append("i.custom_category_name = %s")
		params.append(filters.get("category_name"))

	# Item Type filter (MultiSelectList - can be list or string)
	item_type_filter = filters.get("item_type")
	if item_type_filter:
		if isinstance(item_type_filter, str):
			item_types = [item.strip() for item in item_type_filter.split(",") if item.strip()]
		elif isinstance(item_type_filter, list):
			item_types = [item for item in item_type_filter if item]
		else:
			item_types = [item_type_filter] if item_type_filter else []

		if item_types:
			placeholders = ",".join(["%s"] * len(item_types))
			conditions.append(f"i.custom_item_type IN ({placeholders})")
			params.extend(item_types)

	# Buffer Flag filter
	buffer_flag_filter = filters.get("buffer_flag")
	if buffer_flag_filter:
		if buffer_flag_filter == "Buffer":
			conditions.append("i.custom_buffer_flag = 'Buffer'")
		elif buffer_flag_filter == "Non-Buffer":
			conditions.append("(i.custom_buffer_flag != 'Buffer' OR i.custom_buffer_flag IS NULL)")

	# Build SQL query
	where_clause = " AND ".join(conditions)
	query = f"""
		SELECT
			i.name as item_code,
			i.custom_item_type as item_type,
			i.item_group,
			i.custom_category_name as category_name,
			i.custom_buffer_flag as buffer_flag
		FROM
			`tabItem` i
		WHERE
			{where_clause}
		ORDER BY
			i.name
	"""

	# Get all items with required fields
	items = frappe.db.sql(query, tuple(params) if params else (), as_dict=True)

	if not items:
		return []

	# Get item codes
	item_codes = [item.item_code for item in items]

	# Get stock for all items (sum across all warehouses)
	if item_codes:
		stock_data = frappe.db.sql(
			"""
			SELECT
				item_code,
				SUM(actual_qty) as stock
			FROM
				`tabBin`
			WHERE
				item_code IN %s
			GROUP BY
				item_code
			""",
			(tuple(item_codes) if len(item_codes) > 1 else (item_codes[0],),),
			as_dict=True,
		)
		stock_map = {d.item_code: flt(d.stock) for d in stock_data}
	else:
		stock_map = {}

	# Get qualified demand map (open SO quantity)
	qualified_demand_map = get_qualified_demand_map(filters)

	# SKU Type filter (applied after calculation since SKU type is calculated)
	sku_type_filter = filters.get("sku_type")
	if sku_type_filter:
		if isinstance(sku_type_filter, str):
			sku_types = [sku.strip() for sku in sku_type_filter.split(",") if sku.strip()]
		elif isinstance(sku_type_filter, list):
			sku_types = [sku for sku in sku_type_filter if sku]
		else:
			sku_types = [sku_type_filter] if sku_type_filter else []
	else:
		sku_types = []

	# Prepare data
	data = []
	for item in items:
		item_code = item.item_code
		buffer_flag = item.get("buffer_flag") or "Non-Buffer"
		item_type = item.get("item_type")

		# Calculate SKU type
		sku_type = calculate_sku_type(buffer_flag, item_type)

		# Apply SKU Type filter (if specified)
		if sku_types and sku_type not in sku_types:
			continue

		# Get store stock (total stock across all warehouses)
		store_stock = flt(stock_map.get(item_code, 0))

		# Get open SO quantity
		open_so_qty = flt(qualified_demand_map.get(item_code, 0))

		# Calculate pre stock = store stock - open SO quantity
		free_stock = store_stock - open_so_qty

		data.append(
			{
				"item_code": item_code,
				"sku_type": sku_type,
				"item_type": item_type,
				"item_group": item.get("item_group"),
				"category_name": item.get("category_name"),
				"buffer_flag": buffer_flag,
				"store_stock": store_stock,
				"free_stock": free_stock,
			}
		)

	return data

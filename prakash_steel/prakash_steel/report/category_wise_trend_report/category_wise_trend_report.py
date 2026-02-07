# Copyright (c) 2026, beetashoke chakraborty and contributors
# For license information, please see license.txt

import frappe
import math
from frappe import _
from frappe.utils import getdate, date_diff, add_days, flt, today


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


def execute(filters=None):
	if not filters:
		filters = {}

	# Return empty result if filters are not provided (initial load)
	if not filters.get("from_date") or not filters.get("to_date") or not filters.get("sku_type"):
		sku_type = filters.get("sku_type", "")
		label = f"{sku_type} Availability" if sku_type else "SKU Type Availability"
		return [{"fieldname": "category", "label": _(label), "fieldtype": "Data", "width": 200}], []

	from_date = getdate(filters.get("from_date"))
	to_date = getdate(filters.get("to_date"))
	sku_type = filters.get("sku_type")

	if from_date > to_date:
		frappe.throw(_("From Date cannot be greater than To Date"))

	# Generate date columns dynamically
	columns = get_columns(from_date, to_date, sku_type)

	# Get data
	data = get_data(from_date, to_date, sku_type)

	return columns, data


def get_columns(from_date, to_date, sku_type):
	"""Generate columns: {SKU Type} Availability, then one column for each date in range"""
	label = f"{sku_type} Availability"
	columns = [{"fieldname": "category", "label": _(label), "fieldtype": "Data", "width": 200}]

	# Add a column for each date in the range
	current_date = from_date
	while current_date <= to_date:
		date_str = current_date.strftime("%d %b %Y")
		fieldname = f"date_{current_date.strftime('%Y_%m_%d')}"

		columns.append({"fieldname": fieldname, "label": date_str, "fieldtype": "Data", "width": 120})

		current_date = add_days(current_date, 1)

	return columns


def get_data(from_date, to_date, sku_type):
	"""Query data and build report data for categories"""

	# Handle special cases: Pending SO and Open PO
	if sku_type == "Pending SO":
		return get_pending_so_data(from_date, to_date)
	elif sku_type == "Open PO":
		return get_open_po_data(from_date, to_date)

	# Original logic for SKU types (BBMTA, RBMTA, etc.)
	# Get all dates in range
	date_list = []
	current_date = from_date
	while current_date <= to_date:
		date_list.append(current_date)
		current_date = add_days(current_date, 1)

	# Query Item wise Daily On Hand Colour for the date range
	parent_docs = frappe.db.sql(
		"""
		SELECT name, posting_date
		FROM `tabItem wise Daily On Hand Colour`
		WHERE posting_date BETWEEN %s AND %s
		ORDER BY posting_date
	""",
		(from_date, to_date),
		as_dict=True,
	)

	# Build a map: {date: {item_code: on_hand_colour}}
	date_item_colour_map = {}
	for date in date_list:
		date_item_colour_map[date] = {}

	# Process each parent document
	for parent_doc in parent_docs:
		posting_date = getdate(parent_doc.posting_date)

		# Get child table data for this parent
		child_data = frappe.db.sql(
			"""
			SELECT item_code, on_hand_colour
			FROM `tabOn hand colour table`
			WHERE parent = %s AND sku_type = %s
		""",
			(parent_doc.name, sku_type),
			as_dict=True,
		)

		# Store the on_hand_colour for each item on this date
		if posting_date in date_item_colour_map:
			for child in child_data:
				item_code = child.item_code
				on_hand_colour = child.on_hand_colour
				if item_code:
					date_item_colour_map[posting_date][item_code] = on_hand_colour or ""

	# Get all unique items across all dates for the selected SKU type
	all_items = set()
	for date in date_list:
		all_items.update(date_item_colour_map[date].keys())

	# Get current buffer status and item type for all items
	# Only include items that are currently buffer items with the selected SKU type
	valid_items = set()
	if all_items:
		items_data = frappe.db.sql(
			"""
			SELECT name, item_name, custom_buffer_flag, custom_item_type
			FROM `tabItem`
			WHERE name IN ({})
		""".format(",".join(["%s"] * len(all_items))),
			tuple(all_items),
			as_dict=True,
		)

		for item in items_data:
			buffer_flag = item.get("custom_buffer_flag") or "Non-Buffer"
			item_type = item.get("custom_item_type")
			current_sku_type = calculate_sku_type(buffer_flag, item_type)

			# Only include items that currently have the selected SKU type
			if current_sku_type == sku_type:
				valid_items.add(item.name)

	# Define the 5 categories
	categories = ["Black", "Red", "Yellow", "Green", "White"]

	# First, calculate counts for each category for each date
	category_counts = {}
	for category in categories:
		category_counts[category] = {}
		for date in date_list:
			count = 0
			# Count items that have this category's colour on this date
			for item_code in valid_items:
				on_hand_colour = date_item_colour_map[date].get(item_code, "")
				if on_hand_colour and on_hand_colour.strip().upper() == category.upper():
					count += 1
			category_counts[category][date] = count

	# Calculate total count for each date (sum of all categories)
	date_totals = {}
	for date in date_list:
		total = 0
		for category in categories:
			total += category_counts[category][date]
		date_totals[date] = total

	# Build report data rows - one row for each category with percentages
	data = []
	for category in categories:
		row = {"category": category}

		# For each date, calculate percentage
		for date in date_list:
			fieldname = f"date_{date.strftime('%Y_%m_%d')}"
			count = category_counts[category][date]
			total = date_totals[date]

			# Calculate percentage and round
			if total > 0:
				percentage = (count / total) * 100
				percentage_rounded = round(percentage)
				row[fieldname] = f"{percentage_rounded}%"
			else:
				row[fieldname] = "0%"

		data.append(row)

	return data


def calculate_order_status(delivery_date, transaction_date, check_date):
	"""Calculate order status (BLACK, RED, YELLOW, GREEN, WHITE) based on buffer_status logic"""
	if not delivery_date or not transaction_date:
		return "BLACK"

	delay_days = date_diff(check_date, delivery_date)
	remaining_days = -flt(delay_days)
	lead_time = date_diff(delivery_date, transaction_date)

	buffer_status = None
	if remaining_days is not None:
		if flt(remaining_days) == 0:
			buffer_status = 0
		elif lead_time and lead_time > 0:
			buffer_status = (flt(remaining_days) / flt(lead_time)) * 100
		else:
			buffer_status = flt(remaining_days) * 100

	numeric_status = None
	if buffer_status is not None:
		numeric_status = math.ceil(buffer_status)

	if numeric_status is None:
		return "BLACK"
	elif numeric_status < 0:
		return "BLACK"
	elif numeric_status == 0:
		return "RED"
	elif 1 <= numeric_status <= 34:
		return "RED"
	elif 35 <= numeric_status <= 67:
		return "YELLOW"
	elif 68 <= numeric_status <= 100:
		return "GREEN"
	else:
		return "WHITE"


def get_pending_so_data(from_date, to_date):
	"""Get Pending SO data with color status for each date"""
	# Get all dates in range
	date_list = []
	current_date = from_date
	while current_date <= to_date:
		date_list.append(current_date)
		current_date = add_days(current_date, 1)

	# Get all Sales Orders with status 'To Deliver and Bill' that existed during the date range
	# We need to get SOs that were active at any point during the date range
	so_data = frappe.db.sql(
		"""
		SELECT
			so.name as sales_order,
			so.transaction_date as date,
			MIN(soi.delivery_date) as delivery_date
		FROM
			`tabSales Order` so
		INNER JOIN
			`tabSales Order Item` soi ON soi.parent = so.name
		WHERE
			so.status = 'To Deliver and Bill'
			AND so.status NOT IN ('Stopped', 'On Hold', 'Closed', 'Cancelled')
			AND so.docstatus = 1
			AND (soi.qty - IFNULL(soi.delivered_qty, 0)) > 0
			AND so.transaction_date <= %s
		GROUP BY
			so.name, so.transaction_date
		""",
		(to_date,),  # Use to_date instead of today() to include historical data
		as_dict=1,
	)

	# Calculate status for each SO on each date
	categories = ["Black", "Red", "Yellow", "Green", "White"]
	category_counts = {}
	for category in categories:
		category_counts[category] = {}
		for date in date_list:
			category_counts[category][date] = 0

	for so in so_data:
		delivery_date = so.get("delivery_date")
		transaction_date = so.get("date")

		# Calculate status for each date in range
		# Only count this SO if it existed on this date (transaction_date <= check_date)
		for date in date_list:
			if transaction_date and getdate(transaction_date) <= date:
				order_status = calculate_order_status(delivery_date, transaction_date, date)
				if order_status.upper() in [c.upper() for c in categories]:
					category_counts[order_status.capitalize()][date] += 1

	# Calculate totals and percentages
	date_totals = {}
	for date in date_list:
		total = 0
		for category in categories:
			total += category_counts[category][date]
		date_totals[date] = total

	# Build report data
	data = []
	for category in categories:
		row = {"category": category}
		for date in date_list:
			fieldname = f"date_{date.strftime('%Y_%m_%d')}"
			count = category_counts[category][date]
			total = date_totals[date]

			if total > 0:
				percentage = (count / total) * 100
				percentage_rounded = round(percentage)
				row[fieldname] = f"{percentage_rounded}%"
			else:
				row[fieldname] = "0%"

		data.append(row)

	return data


def get_open_po_data(from_date, to_date):
	"""Get Open PO data - placeholder (no logic implemented yet, same as prakash_steel_planni)"""
	# Get all dates in range
	date_list = []
	current_date = from_date
	while current_date <= to_date:
		date_list.append(current_date)
		current_date = add_days(current_date, 1)

	# Placeholder: Return empty data (0% for all categories) since Open PO logic is not implemented yet
	# This matches the behavior in prakash_steel_planni where get_open_po_status() is just a placeholder
	categories = ["Black", "Red", "Yellow", "Green", "White"]

	# Build report data with 0% for all categories and dates
	data = []
	for category in categories:
		row = {"category": category}
		for date in date_list:
			fieldname = f"date_{date.strftime('%Y_%m_%d')}"
			row[fieldname] = "0%"

		data.append(row)

	return data

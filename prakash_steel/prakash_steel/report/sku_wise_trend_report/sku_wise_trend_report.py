# Copyright (c) 2026, beetashoke chakraborty and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, date_diff, add_days


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
		return [
			{
				"fieldname": "item_name",
				"label": _("Item Name"),
				"fieldtype": "Link",
				"options": "Item",
				"width": 200,
			}
		], []

	from_date = getdate(filters.get("from_date"))
	to_date = getdate(filters.get("to_date"))
	sku_type = filters.get("sku_type")
	item_code_filter = filters.get("item_code")  # Can be a list or single value

	if from_date > to_date:
		frappe.throw(_("From Date cannot be greater than To Date"))

	# Generate date columns dynamically
	columns = get_columns(from_date, to_date)

	# Get data
	data = get_data(from_date, to_date, sku_type, item_code_filter)

	return columns, data


def get_columns(from_date, to_date):
	"""Generate columns: Item Name, then one column for each date in range"""
	columns = [
		{
			"fieldname": "item_name",
			"label": _("Item Name"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 200,
		}
	]

	# Add a column for each date in the range
	current_date = from_date
	while current_date <= to_date:
		date_str = current_date.strftime("%d %b %Y")
		fieldname = f"date_{current_date.strftime('%Y_%m_%d')}"

		columns.append({"fieldname": fieldname, "label": date_str, "fieldtype": "Data", "width": 120})

		current_date = add_days(current_date, 1)

	return columns


def get_data(from_date, to_date, sku_type, item_code_filter=None):
	"""Query Item wise Daily On Hand Colour and build report data"""

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

	# Process item_code filter - convert to list if it's a string or list
	filtered_item_codes = None
	if item_code_filter:
		if isinstance(item_code_filter, str):
			# If it's a string, convert to list (handles single item or comma-separated)
			filtered_item_codes = [item.strip() for item in item_code_filter.split(",") if item.strip()]
		elif isinstance(item_code_filter, list):
			filtered_item_codes = [item for item in item_code_filter if item]

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
				# Apply item_code filter if provided
				if filtered_item_codes is None or item.name in filtered_item_codes:
					valid_items.add(item.name)

	# Get item names for valid items only
	item_names = {}
	if valid_items:
		items_data = frappe.db.sql(
			"""
			SELECT name, item_name
			FROM `tabItem`
			WHERE name IN ({})
		""".format(",".join(["%s"] * len(valid_items))),
			tuple(valid_items),
			as_dict=True,
		)

		for item in items_data:
			item_names[item.name] = item.item_name or item.name

	# Build report data rows - only for items that are currently buffer items
	data = []
	for item_code in sorted(valid_items):
		row = {
			"item_name": item_code,  # Use item_code for Link field
			"item_code": item_code,  # Store item_code for reference
		}

		# Add on_hand_colour for each date
		for date in date_list:
			fieldname = f"date_{date.strftime('%Y_%m_%d')}"
			on_hand_colour = date_item_colour_map[date].get(item_code, "")
			row[fieldname] = on_hand_colour

		data.append(row)

	return data

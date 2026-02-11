# Copyright (c) 2025, beetashoke chakraborty and contributors
# For license information, please see license.txt

import math
import frappe
from frappe import _
from frappe.utils import flt
from prakash_steel.utils.lead_time import get_default_bom


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


def calculate_net_order_recommendation(base_order_rec, moq, batch_size):
	"""Calculate net order recommendation by applying MOQ/Batch Size logic"""
	base_order_rec = flt(base_order_rec)
	moq = flt(moq)
	batch_size = flt(batch_size)

	if base_order_rec <= 0:
		return 0

	if moq > 0:
		if moq < base_order_rec:
			net_order_rec = base_order_rec
		else:
			net_order_rec = moq
	elif batch_size > 0:
		net_order_rec = math.ceil(base_order_rec / batch_size) * batch_size
	else:
		net_order_rec = base_order_rec

	return max(0, flt(net_order_rec))


def calculate_initial_order_recommendation(
	item_code,
	item_buffer_map,
	item_tog_map,
	item_sku_type_map,
	stock_map,
	wip_map,
	open_so_map,
	qualified_demand_map,
	open_po_map,
):
	"""Calculate initial order recommendation for a single item (before BOM traversal)"""
	buffer_flag = item_buffer_map.get(item_code, "Non-Buffer")
	is_buffer = buffer_flag == "Buffer"

	stock = flt(stock_map.get(item_code, 0))
	wip = flt(wip_map.get(item_code, 0))

	if is_buffer:
		tog = flt(item_tog_map.get(item_code, 0))
		qualified_demand = flt(qualified_demand_map.get(item_code, 0))
		sku_type = item_sku_type_map.get(item_code)
		open_po = flt(open_po_map.get(item_code, 0))

		if sku_type in ["PTA", "SFGMTA"]:
			order_rec = max(0, tog + qualified_demand - stock - wip - open_po)
		else:
			order_rec = max(0, tog + qualified_demand - stock - wip)
	else:
		qualified_demand = flt(qualified_demand_map.get(item_code, 0))
		sku_type = item_sku_type_map.get(item_code)
		open_po = flt(open_po_map.get(item_code, 0))

		if sku_type in ["PTO", "BOTO"]:
			order_rec = max(0, qualified_demand - stock - wip - open_po)
		else:
			order_rec = max(0, qualified_demand - stock - wip)

	return order_rec


def calculate_final_order_recommendation(
	item_code,
	item_buffer_map,
	item_tog_map,
	item_sku_type_map,
	stock_map,
	wip_map,
	open_so_map,
	qualified_demand_map,
	open_po_map,
	mrq_map,
	parent_demand_map,
):
	"""Calculate final order recommendation for a single item (after BOM traversal)"""
	buffer_flag = item_buffer_map.get(item_code, "Non-Buffer")
	is_buffer = buffer_flag == "Buffer"

	stock = flt(stock_map.get(item_code, 0))
	wip = flt(wip_map.get(item_code, 0))
	mrq = flt(mrq_map.get(item_code, 0))

	if is_buffer:
		tog = flt(item_tog_map.get(item_code, 0))
		qualified_demand = flt(qualified_demand_map.get(item_code, 0))
		sku_type = item_sku_type_map.get(item_code)
		open_po = flt(open_po_map.get(item_code, 0))

		if sku_type in ["BOTA", "PTA"]:
			base_order_rec = tog + qualified_demand - stock - wip - open_po
		else:
			base_order_rec = tog + qualified_demand - stock - wip

		order_rec = max(0, base_order_rec - mrq)
	else:
		qualified_demand = flt(qualified_demand_map.get(item_code, 0))
		parent_demand = flt(parent_demand_map.get(item_code, 0))
		requirement = qualified_demand + parent_demand
		sku_type = item_sku_type_map.get(item_code)
		open_po = flt(open_po_map.get(item_code, 0))

		if sku_type in ["PTO", "BOTO"]:
			base_order_rec = requirement - stock - wip - open_po
		else:
			base_order_rec = requirement - stock - wip

		order_rec = max(0, base_order_rec - mrq)

	return order_rec


def execute(filters=None):
	columns = get_columns(filters)
	data = get_data(filters)
	return columns, data


def save_daily_on_hand_colour():
	"""Scheduled job to save daily on hand colour for buffer items"""
	from frappe.utils import nowdate

	posting_date = nowdate()
	all_data = []
	seen_item_codes = {}

	try:
		filters_purchase = {"purchase": 1, "buffer_flag": 1}
		_, data_purchase = execute(filters_purchase)
		if data_purchase:
			for row in data_purchase:
				item_code = row.get("item_code")
				if item_code and item_code not in seen_item_codes:
					seen_item_codes[item_code] = row
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "save_daily_on_hand_colour: execute (purchase) failed")

	try:
		filters_sell = {"sell": 1, "buffer_flag": 1}
		_, data_sell = execute(filters_sell)
		if data_sell:
			for row in data_sell:
				item_code = row.get("item_code")
				if item_code and item_code not in seen_item_codes:
					seen_item_codes[item_code] = row
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "save_daily_on_hand_colour: execute (sell) failed")

	all_data = list(seen_item_codes.values())

	if not all_data:
		return

	try:
		doc = frappe.new_doc("Item wise Daily On Hand Colour")
		doc.posting_date = posting_date
		saved_rows = 0

		for row in all_data:
			item_code = row.get("item_code")
			sku_type = row.get("sku_type")
			on_hand_colour = row.get("on_hand_colour")

			if not item_code or not on_hand_colour:
				continue

			child = doc.append("item_wise_on_hand_colour", {})
			child.item_code = item_code
			child.sku_type = sku_type
			child.on_hand_colour = on_hand_colour
			saved_rows += 1

		if saved_rows == 0:
			return

		doc.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception as e:
		frappe.log_error(
			frappe.get_traceback(), "save_daily_on_hand_colour: failed to create snapshot document"
		)


def get_columns(filters=None):
	if not filters:
		filters = {}

	# Check if "Sell" is selected
	sell = filters.get("sell", 0)
	if isinstance(sell, str):
		sell = 1 if sell in ("1", "true", "True") else 0
	sell = int(sell) if sell else 0

	# Check if "Buffer Flag" is selected
	buffer_flag = filters.get("buffer_flag", 0)
	if isinstance(buffer_flag, str):
		buffer_flag = 1 if buffer_flag in ("1", "true", "True") else 0
	buffer_flag = int(buffer_flag) if buffer_flag else 0

	columns = [
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
			"label": _("Sequence"),
			"fieldname": "sequence",
			"fieldtype": "Data",
			"width": 80,
		},
	]

	# Add "Requirement" column for non-buffer items (after SKU Type)
	if not buffer_flag:
		columns.append(
			{
				"label": _("Requirement"),
				"fieldname": "requirement",
				"fieldtype": "Int",
				"width": 120,
			}
		)

	# Add TOG, TOY, TOR columns only for buffer items
	if buffer_flag:
		columns.extend(
			[
				{
					"label": _("TOG"),
					"fieldname": "tog",
					"fieldtype": "Int",
					"width": 100,
				},
				{
					"label": _("TOY"),
					"fieldname": "toy",
					"fieldtype": "Int",
					"width": 100,
				},
				{
					"label": _("TOR"),
					"fieldname": "tor",
					"fieldtype": "Int",
					"width": 100,
				},
			]
		)

	# Add columns based on buffer_flag
	if buffer_flag:
		# For buffer items: Open SO and Qualified Demand
		columns.extend(
			[
				{
					"label": _("Open SO"),
					"fieldname": "open_so",
					"fieldtype": "Int",
					"width": 120,
				},
				{
					"label": _("On Hand Stock"),
					"fieldname": "on_hand_stock",
					"fieldtype": "Int",
					"width": 130,
				},
				{
					"label": _("WIP/Open PO"),
					"fieldname": "wip_open_po",
					"fieldtype": "Int",
					"width": 120,
				},
				{
					"label": _("Qualified Demand"),
					"fieldname": "qualify_demand",
					"fieldtype": "Int",
					"width": 130,
				},
				{
					"label": _("On Hand Status"),
					"fieldname": "on_hand_status",
					"fieldtype": "Data",
					"width": 130,
				},
				{
					"label": _("On Hand Colour"),
					"fieldname": "on_hand_colour",
					"fieldtype": "Data",
					"width": 130,
				},
			]
		)
	else:
		# For non-buffer items: Open SO, Total SO, On Hand Stock, WIP/Open PO, Qualified Demand, Open SO (qualified)
		columns.extend(
			[
				{
					"label": _("Open SO"),
					"fieldname": "open_so",
					"fieldtype": "Int",
					"width": 120,
					"hidden": 1,
				},
				{
					"label": _("Total SO"),
					"fieldname": "total_so",
					"fieldtype": "Int",
					"width": 120,
				},
				{
					"label": _("Open SO"),
					"fieldname": "open_so_qualified",
					"fieldtype": "Int",
					"width": 120,
				},
				{
					"label": _("On Hand Stock"),
					"fieldname": "on_hand_stock",
					"fieldtype": "Int",
					"width": 130,
				},
				{
					"label": _("WIP/Open PO"),
					"fieldname": "wip_open_po",
					"fieldtype": "Int",
					"width": 120,
				},
				{
					"label": _("Qualified Demand"),
					"fieldname": "qualify_demand",
					"fieldtype": "Int",
					"width": 130,
					"hidden": 1,
				},
			]
		)

	# Add remaining common columns
	columns.extend(
		[
			{
				"label": _("Order Recommendation"),
				"fieldname": "order_recommendation",
				"fieldtype": "Int",
				"width": 180,
			},
			{
				"label": _("MRQ"),
				"fieldname": "mrq",
				"fieldtype": "Int",
				"width": 120,
			},
			{
				"label": _("Balance Order Recommendation"),
				"fieldname": "net_po_recommendation",
				"fieldtype": "Int",
				"width": 180,
			},
			{
				"label": _("Net Order Recommendation"),
				"fieldname": "or_with_moq_batch_size",
				"fieldtype": "Int",
				"width": 180,
			},
			{
				"label": _("MOQ"),
				"fieldname": "moq",
				"fieldtype": "Int",
				"width": 120,
			},
			{
				"label": _("Order Multiple Qty"),
				"fieldname": "batch_size",
				"fieldtype": "Int",
				"width": 120,
			},
		]
	)

	# Only add child-related columns if "Sell" is selected (hide for Purchase)
	if sell:
		columns.extend(
			[
				{
					"label": _("Production qty based on child stock Ind"),
					"fieldname": "production_qty_based_on_child_stock",
					"fieldtype": "Int",
					"width": 220,
				},
				{
					"label": _("Production qty based on child stock"),
					"fieldname": "minimum_qty_based_on_child_stock",
					"fieldtype": "Int",
					"width": 220,
				},
				{
					"label": _("Child Stock Full-Kit Status"),
					"fieldname": "child_full_kit_status",
					"fieldtype": "Data",
					"width": 160,
				},
				{
					"label": _("Production qty based on child stock+WIP/Open PO Ind"),
					"fieldname": "production_qty_based_on_child_stock_wip_open_po",
					"fieldtype": "Int",
					"width": 280,
				},
				{
					"label": _("Production qty based on child stock+wip/open po"),
					"fieldname": "minimum_qty_based_on_child_stock_wip_open_po",
					"fieldtype": "Int",
					"width": 280,
				},
				{
					"label": _("Child Stock + WIP/Open PO Full-Kit Status"),
					"fieldname": "child_wip_open_po_full_kit_status",
					"fieldtype": "Data",
					"width": 160,
				},
				{
					"label": _("Child Item Code"),
					"fieldname": "child_item_code",
					"fieldtype": "Link",
					"options": "Item",
					"width": 150,
				},
				{
					"label": _("Child Item Type"),
					"fieldname": "child_item_type",
					"fieldtype": "Data",
					"width": 130,
				},
				{
					"label": _("Child SKU Type"),
					"fieldname": "child_sku_type",
					"fieldtype": "Data",
					"width": 130,
				},
				{
					"label": _("Child Requirement"),
					"fieldname": "child_requirement",
					"fieldtype": "Int",
					"width": 150,
				},
				{
					"label": _("Child stock"),
					"fieldname": "child_stock",
					"fieldtype": "Int",
					"width": 120,
				},
				{
					"label": _("Child stock soft allocation qty"),
					"fieldname": "child_traditional_stock_allocation",
					"fieldtype": "Int",
					"width": 220,
					"hidden": 1,
				},
				{
					"label": _("Child Stock soft Allocation qty"),
					"fieldname": "child_stock_soft_allocation_qty",
					"fieldtype": "Int",
					"width": 200,
				},
				# {
				# 	"label": _("Child traditional stock allocation"),
				# 	"fieldname": "child_traditional_stock_allocation",
				# 	"fieldtype": "Int",
				# 	"width": 220,
				# },
				{
					"label": _("Child Stock shortage"),
					"fieldname": "child_stock_shortage",
					"fieldtype": "Int",
					"width": 160,
				},
				{
					"label": _("Child WIP/Open PO"),
					"fieldname": "child_wip_open_po",
					"fieldtype": "Int",
					"width": 150,
				},
				{
					"label": _("Child wip/open po soft allocation qty"),
					"fieldname": "child_traditional_wip_open_po_soft_allocation",
					"fieldtype": "Int",
					"width": 280,
					"hidden": 1,
				},
				{
					"label": _("Child WIP/Open PO soft allocation qty"),
					"fieldname": "child_wip_open_po_soft_allocation_qty",
					"fieldtype": "Int",
					"width": 250,
				},
				# {
				# 	"label": _("Child traditional wip/open po soft allocation"),
				# 	"fieldname": "child_traditional_wip_open_po_soft_allocation",
				# 	"fieldtype": "Int",
				# 	"width": 280,
				# },
				{
					"label": _("Child WIP/Open PO Shortage"),
					"fieldname": "child_wip_open_po_shortage",
					"fieldtype": "Int",
					"width": 200,
				},
			]
		)

	return columns


def get_data(filters=None):
	"""Get buffer items and calculate PO recommendations"""
	if not filters:
		filters = {}

	purchase = filters.get("purchase", 0)
	sell = filters.get("sell", 0)
	buffer_flag = filters.get("buffer_flag", 0)

	if isinstance(purchase, str):
		purchase = 1 if purchase in ("1", "true", "True") else 0
	if isinstance(sell, str):
		sell = 1 if sell in ("1", "true", "True") else 0
	if isinstance(buffer_flag, str):
		buffer_flag = 1 if buffer_flag in ("1", "true", "True") else 0

	purchase = int(purchase) if purchase else 0
	sell = int(sell) if sell else 0
	buffer_flag = int(buffer_flag) if buffer_flag else 0

	if not (purchase or sell):
		return []

	allowed_sku_types = []
	if purchase:
		if buffer_flag:
			# Purchase + Buffer: PTA (RM with buffer)
			allowed_sku_types = ["PTA"]
		else:
			# Purchase + Non-Buffer: PTO (RM without buffer)
			allowed_sku_types = ["PTO"]
	elif sell:
		if buffer_flag:
			# Sell + Buffer: FGMTA (FG with buffer), SFGMTA (INT with buffer)
			allowed_sku_types = ["FGMTA", "SFGMTA"]
		else:
			# Sell + Non-Buffer: FGMTO (FG without buffer), SFGMTO (INT without buffer)
			allowed_sku_types = ["FGMTO", "SFGMTO"]

	# Get sales order qty map (all-time data) - for ALL items
	so_qty_map = get_sales_order_qty_map(filters)

	# Get qualified demand map (Open SO with delivery_date <= today)
	qualified_demand_map = get_qualified_demand_map(filters)

	# Get items from database based on buffer_flag filter
	if buffer_flag:
		# Get buffer items
		items_query = """
			SELECT name as item_code
			FROM `tabItem`
			WHERE custom_buffer_flag = 'Buffer'
		"""
	else:
		# Get non-buffer items
		items_query = """
			SELECT name as item_code
			FROM `tabItem`
			WHERE custom_buffer_flag != 'Buffer' OR custom_buffer_flag IS NULL
		"""

	items_result = frappe.db.sql(items_query, as_dict=1)
	item_codes = set(item.item_code for item in items_result)
	so_qty_map = {k: v for k, v in so_qty_map.items() if k in item_codes}
	wip_map = get_wip_map(filters)
	mrq_map = get_mrq_map(filters)
	open_po_map = get_open_po_map()

	items_with_po = set(open_po_map.keys())
	items_with_po_selected = {item for item in items_with_po if item in item_codes}
	all_items_to_process = item_codes | items_with_po_selected

	if not all_items_to_process:
		return []
	initial_stock_map = get_stock_map(all_items_to_process)
	remaining_stock = dict(initial_stock_map)
	po_recommendations = {}
	item_groups_cache = {}

	parent_demand_map = {}
	items_with_so = set(so_qty_map.keys())
	for item_code in sorted(items_with_so):
		so_qty = flt(so_qty_map.get(item_code, 0))
		available_stock = flt(remaining_stock.get(item_code, 0))

		# Calculate PO recommendation for this item using remaining stock
		required_qty = max(0, so_qty - available_stock)

		# Allocate stock: reduce remaining stock by what we use
		allocated = min(so_qty, available_stock)
		remaining_stock[item_code] = available_stock - allocated

		# Add to PO recommendations
		if item_code in po_recommendations:
			po_recommendations[item_code] += required_qty
		else:
			po_recommendations[item_code] = required_qty

		if required_qty > 0:
			traverse_bom_for_po(
				item_code,
				required_qty,
				po_recommendations,
				remaining_stock,
				set(),
				item_groups_cache,
				level=0,
			)
	all_item_codes = all_items_to_process

	# Get item details maps
	if all_item_codes:
		if len(all_item_codes) == 1:
			all_items_tuple = (next(iter(all_item_codes)),)
		else:
			all_items_tuple = tuple(all_item_codes)

		items_details_all = frappe.db.sql(
			"""
			SELECT
				i.name as item_code,
				i.custom_buffer_flag as buffer_flag,
				i.custom_item_type as item_type,
				i.safety_stock as tog
			FROM
				`tabItem` i
			WHERE
				i.name IN %s
			""",
			(all_items_tuple,),
			as_dict=1,
		)

		item_buffer_map_all = {}
		item_sku_type_map_all = {}
		item_tog_map_all = {}
		for item in items_details_all:
			item_buffer_map_all[item.item_code] = item.buffer_flag or "Non-Buffer"
			item_sku_type_map_all[item.item_code] = calculate_sku_type(
				item.buffer_flag or "Non-Buffer", item.item_type
			)
			item_tog_map_all[item.item_code] = flt(item.tog or 0)
	else:
		item_buffer_map_all = {}
		item_sku_type_map_all = {}
		item_tog_map_all = {}

	initial_order_recommendations = {}
	for item_code in all_item_codes:
		order_rec = calculate_initial_order_recommendation(
			item_code,
			item_buffer_map_all,
			item_tog_map_all,
			item_sku_type_map_all,
			initial_stock_map,
			wip_map,
			so_qty_map,
			qualified_demand_map,
			open_po_map,
		)
		initial_order_recommendations[item_code] = order_rec
	initial_net_order_recommendations = {}

	if all_item_codes:
		items_moq_batch_data = frappe.db.sql(
			"""
			SELECT
				i.name as item_code,
				i.min_order_qty as moq,
				i.custom_batch_size as batch_size
			FROM
				`tabItem` i
			WHERE
				i.name IN %s
			""",
			(all_items_tuple,),
			as_dict=1,
		)

		moq_map_all = {item.item_code: flt(item.moq or 0) for item in items_moq_batch_data}
		batch_size_map_all = {item.item_code: flt(item.batch_size or 0) for item in items_moq_batch_data}

		for item_code in all_item_codes:
			base_order_rec = initial_order_recommendations.get(item_code, 0)
			moq = moq_map_all.get(item_code, 0)
			batch_size = batch_size_map_all.get(item_code, 0)
			net_order_rec = calculate_net_order_recommendation(base_order_rec, moq, batch_size)
			initial_net_order_recommendations[item_code] = net_order_rec
	else:
		moq_map_all = {}
		batch_size_map_all = {}

	items_to_process = [
		(item_code, net_order_rec)
		for item_code, net_order_rec in initial_net_order_recommendations.items()
		if net_order_rec > 0
	]
	items_to_process.sort(key=lambda x: x[0])

	for item_code, net_order_rec in items_to_process:
		traverse_bom_for_parent_demand_simple(
			item_code,
			net_order_rec,
			parent_demand_map,
			set(),
			item_groups_cache,
			item_buffer_map_all,
			level=0,
		)

	final_order_recommendations = {}
	for item_code in all_item_codes:
		order_rec = calculate_final_order_recommendation(
			item_code,
			item_buffer_map_all,
			item_tog_map_all,
			item_sku_type_map_all,
			initial_stock_map,
			wip_map,
			qualified_demand_map,
			qualified_demand_map,
			open_po_map,
			mrq_map,
			parent_demand_map,
		)
		final_order_recommendations[item_code] = order_rec

	net_order_recommendations = {}
	for item_code in all_item_codes:
		base_order_rec = final_order_recommendations.get(item_code, 0)
		moq = moq_map_all.get(item_code, 0)
		batch_size = batch_size_map_all.get(item_code, 0)
		net_order_rec = calculate_net_order_recommendation(base_order_rec, moq, batch_size)
		net_order_recommendations[item_code] = net_order_rec
	parent_demand_map_net = {}
	items_with_net_rec = [
		(item_code, net_rec) for item_code, net_rec in net_order_recommendations.items() if net_rec > 0
	]
	items_with_net_rec.sort(key=lambda x: x[0])

	global_visited_items = set()

	for item_code, net_rec in items_with_net_rec:
		if item_code not in global_visited_items:
			traverse_bom_for_parent_demand(
				item_code,
				net_rec,
				parent_demand_map_net,
				global_visited_items,
				item_groups_cache,
				qualified_demand_map,
				initial_stock_map,
				wip_map,
				open_po_map,
				mrq_map,
				moq_map_all,
				batch_size_map_all,
				item_buffer_map_all,
				item_sku_type_map_all,
				lambda item_code: None,
				level=0,
			)
	final_order_recommendations_updated = {}
	net_order_recommendations_final = {}

	for item_code in all_item_codes:
		order_rec = calculate_final_order_recommendation(
			item_code,
			item_buffer_map_all,
			item_tog_map_all,
			item_sku_type_map_all,
			initial_stock_map,
			wip_map,
			qualified_demand_map,
			qualified_demand_map,
			open_po_map,
			mrq_map,
			parent_demand_map_net,
		)
		final_order_recommendations_updated[item_code] = order_rec

		moq = moq_map_all.get(item_code, 0)
		batch_size = batch_size_map_all.get(item_code, 0)
		net_order_rec = calculate_net_order_recommendation(order_rec, moq, batch_size)
		net_order_recommendations_final[item_code] = net_order_rec

	final_order_recommendations = final_order_recommendations_updated
	net_order_recommendations = net_order_recommendations_final
	parent_demand_map = parent_demand_map_net  # Use updated parent demands
	all_items_to_show = all_items_to_process

	# Get item details for all items to show
	if not all_items_to_show:
		return []

	# Build item codes tuple for SQL
	if len(all_items_to_show) == 1:
		item_codes_tuple = (next(iter(all_items_to_show)),)
	else:
		item_codes_tuple = tuple(all_items_to_show)
	if buffer_flag:
		items_data = frappe.db.sql(
			"""
			SELECT
				i.name as item_code,
				i.item_name,
				i.safety_stock as tog,
				i.custom_top_of_yellow as toy,
				i.custom_top_of_red as tor,
				i.custom_item_type as item_type,
				i.custom_batch_size as batch_size,
				i.min_order_qty as moq,
				i.custom_buffer_flag as buffer_flag
			FROM
				`tabItem` i
			WHERE
				i.name IN %s
				AND i.custom_buffer_flag = 'Buffer'
			""",
			(item_codes_tuple,),
			as_dict=1,
		)
	else:
		items_data = frappe.db.sql(
			"""
			SELECT
				i.name as item_code,
				i.item_name,
				i.safety_stock as tog,
				i.custom_top_of_yellow as toy,
				i.custom_top_of_red as tor,
				i.custom_item_type as item_type,
				i.custom_batch_size as batch_size,
				i.min_order_qty as moq,
				i.custom_buffer_flag as buffer_flag
			FROM
				`tabItem` i
			WHERE
				i.name IN %s
				AND (i.custom_buffer_flag != 'Buffer' OR i.custom_buffer_flag IS NULL)
			""",
			(item_codes_tuple,),
			as_dict=1,
		)

	# Create a map for quick lookup
	items_map = {item.item_code: item for item in items_data}
	child_stock_map = {}
	child_wip_open_po_map = {}

	data = []
	for item_code in sorted(all_items_to_show):
		item_info = items_map.get(item_code, {})

		# Skip if item is not in items_map
		if not item_info:
			continue

		# Calculate SKU Type based on buffer_flag
		item_type = item_info.get("item_type")
		item_buffer_flag = item_info.get("buffer_flag", "")
		sku_type = calculate_sku_type(item_buffer_flag, item_type)

		# Filter by allowed SKU types (based on Purchase/Sell selection)
		if sku_type not in allowed_sku_types:
			continue

		# Get stock and buffer levels
		on_hand_stock = flt(initial_stock_map.get(item_code, 0))
		tog = flt(item_info.get("tog", 0))
		toy = flt(item_info.get("toy", 0))
		tor = flt(item_info.get("tor", 0))
		# Get Qualified Demand (Open SO with delivery_date <= today)
		qualify_demand = flt(qualified_demand_map.get(item_code, 0))

		# Check if item is buffer or non-buffer
		is_item_buffer = item_buffer_flag == "Buffer"

		on_hand_status_value = None
		on_hand_status = None
		on_hand_colour = None

		if is_item_buffer:
			denominator = flt(tog) + flt(qualify_demand)
			if denominator > 0:
				on_hand_status_value = flt(on_hand_stock) / denominator
			else:
				# If denominator is 0, set to None (cannot calculate)
				on_hand_status_value = None

			numeric_status = None
			if on_hand_status_value is not None:
				numeric_status = math.ceil(on_hand_status_value)

			if numeric_status is None:
				on_hand_colour = None
			elif numeric_status == 0:
				on_hand_colour = "BLACK"
			elif 1 <= numeric_status <= 34:
				on_hand_colour = "RED"
			elif 35 <= numeric_status <= 67:
				on_hand_colour = "YELLOW"
			elif 68 <= numeric_status <= 100:
				on_hand_colour = "GREEN"
			else:  # > 100
				on_hand_colour = "WHITE"

			if numeric_status is not None:
				on_hand_status = f"{int(numeric_status)}%"
			else:
				on_hand_status = None

		# Get item name
		item_name = item_info.get("item_name", "")

		# Get WIP value
		wip = flt(wip_map.get(item_code, 0))

		# Get batch size from item
		batch_size = flt(item_info.get("batch_size", 0))

		# Get MOQ from item
		moq = flt(item_info.get("moq", 0))

		# Get MRQ from Material Requests (sum of quantities from Material Request Items)
		mrq = flt(mrq_map.get(item_code, 0))

		# Get Open PO (Purchase Order quantity - received quantity)
		open_po = flt(open_po_map.get(item_code, 0))

		# Get Open SO
		open_so = flt(so_qty_map.get(item_code, 0))

		# Get parent demand for this item
		parent_demand = flt(parent_demand_map.get(item_code, 0))

		final_order_rec = flt(final_order_recommendations.get(item_code, 0))
		net_order_rec = flt(net_order_recommendations.get(item_code, 0))

		order_recommendation = math.ceil(flt(final_order_rec))
		net_po_recommendation = math.ceil(
			flt(final_order_rec)
		)  # Base order recommendation (before MOQ/Batch Size)
		or_with_moq_batch_size = math.ceil(
			flt(net_order_rec)
		)  # Net order recommendation (after MOQ/Batch Size)

		# Combine WIP and Open PO for display
		wip_open_po = math.ceil(flt(wip) + flt(open_po))

		is_item_buffer = item_buffer_flag == "Buffer"

		if is_item_buffer:
			# Buffer items: use standard column names
			base_row = {
				"item_code": item_code,
				"item_name": item_name,
				"sku_type": sku_type,
				"requirement": None,
				"tog": math.ceil(flt(tog)),
				"toy": math.ceil(flt(toy)),
				"tor": math.ceil(flt(tor)),
				"open_so": math.ceil(flt(open_so)),
				"on_hand_stock": math.ceil(flt(on_hand_stock)),
				"wip_open_po": math.ceil(flt(wip_open_po)),
				"qualify_demand": math.ceil(flt(qualify_demand)),
			}
		else:
			base_row = {
				"item_code": item_code,
				"item_name": item_name,
				"sku_type": sku_type,
				"requirement": math.ceil(flt(parent_demand)),
				"tog": None,
				"toy": None,
				"tor": None,
				"open_so": math.ceil(flt(open_so)),
				"total_so": math.ceil(flt(open_so)),
				"on_hand_stock": math.ceil(flt(on_hand_stock)),
				"wip_open_po": math.ceil(flt(wip_open_po)),
				"qualify_demand": math.ceil(flt(qualify_demand)),
				"open_so_qualified": math.ceil(flt(qualify_demand)),
			}

		# Add common fields
		base_row.update(
			{
				"on_hand_status": on_hand_status,
				"on_hand_colour": on_hand_colour,
				"buffer_flag": item_buffer_flag,  # Add buffer_flag for JavaScript formatter
				"order_recommendation": math.ceil(flt(order_recommendation)),
				"batch_size": math.ceil(flt(batch_size)),
				"moq": math.ceil(flt(moq)),
				"or_with_moq_batch_size": math.ceil(flt(or_with_moq_batch_size)),
				"mrq": math.ceil(flt(mrq)),
				"net_po_recommendation": math.ceil(flt(net_po_recommendation)),
				"batch_size_multiple": None,
				"production_qty_based_on_child_stock": None,
				"production_qty_based_on_child_stock_wip_open_po": None,
				"child_item_code": None,
				"child_item_type": None,
				"child_sku_type": None,
				"child_requirement": None,
				"child_stock": None,
				"child_stock_soft_allocation_qty": None,
				"child_traditional_stock_allocation": None,
				"child_stock_shortage": None,
				"child_full_kit_status": None,
				"child_wip_open_po": None,
				"child_wip_open_po_soft_allocation_qty": None,
				"child_traditional_wip_open_po_soft_allocation": None,
				"child_wip_open_po_shortage": None,
				"child_wip_open_po_full_kit_status": None,
			}
		)

		# Get BOM for this item to find child items
		bom = get_default_bom(item_code)
		child_items = []

		if bom:
			try:
				bom_doc = frappe.get_doc("BOM", bom)
				bom_quantity = flt(bom_doc.quantity) or 1.0
				# Get all child items from BOM
				for bom_item in bom_doc.items:
					child_item_code = bom_item.item_code
					child_bom_qty = flt(bom_item.qty)
					# Store BOM qty and BOM quantity so we can apply the correct ratio later
					child_items.append(
						{
							"item_code": child_item_code,
							"bom_qty": child_bom_qty,
							"bom_quantity": bom_quantity,
						}
					)
			except Exception as e:
				frappe.log_error(
					f"Error getting BOM {bom} for item {item_code}: {str(e)}", "PO Recommendation Error"
				)

		if child_items:
			for child_item_info in child_items:
				child_item_code = child_item_info["item_code"]
				child_bom_qty = flt(child_item_info.get("bom_qty", 0))
				child_bom_quantity = flt(child_item_info.get("bom_quantity", 1.0)) or 1.0

				child_item_type = None
				child_sku_type = None
				child_stock = 0

				try:
					child_item_doc = frappe.get_doc("Item", child_item_code)
					child_item_type = child_item_doc.get("custom_item_type")
					child_buffer_flag = child_item_doc.get("custom_buffer_flag") or "Non-Buffer"
					child_sku_type = calculate_sku_type(child_buffer_flag, child_item_type)

					if child_item_code not in child_stock_map:
						stock_data = frappe.db.sql(
							"""
							SELECT SUM(actual_qty) as stock
							FROM `tabBin`
							WHERE item_code = %s
							""",
							(child_item_code,),
							as_dict=True,
						)
						total_stock = math.ceil(
							flt(stock_data[0].stock if stock_data and stock_data[0].stock else 0)
						)
						child_stock_map[child_item_code] = total_stock

					# Use total stock for display
					child_stock = child_stock_map.get(child_item_code, 0)
				except Exception as e:
					frappe.log_error(
						f"Error fetching child item {child_item_code}: {str(e)}", "PO Recommendation Error"
					)
				normalized_bom_qty = child_bom_qty / child_bom_quantity if child_bom_quantity else 0
				child_requirement = math.ceil(flt(or_with_moq_batch_size) * normalized_bom_qty)

				# Get Child WIP and Open PO (same logic as parent items)
				child_wip = flt(wip_map.get(child_item_code, 0))
				child_open_po = flt(open_po_map.get(child_item_code, 0))
				# Combine WIP and Open PO for display
				child_wip_open_po = math.ceil(flt(child_wip) + flt(child_open_po))
				# Store total WIP/Open PO for this child item (for FIFO allocation)
				if child_item_code not in child_wip_open_po_map:
					child_wip_open_po_map[child_item_code] = child_wip_open_po

				row = base_row.copy()
				row["child_item_code"] = child_item_code
				row["child_item_type"] = child_item_type
				row["child_sku_type"] = child_sku_type
				row["child_requirement"] = child_requirement
				row["child_stock"] = child_stock
				row["child_wip_open_po"] = child_wip_open_po
				row["child_bom_qty"] = child_bom_qty
				row["child_bom_quantity"] = child_bom_quantity
				row["child_stock_soft_allocation_qty"] = None
				row["child_stock_shortage"] = None

				data.append(row)
		else:
			data.append(base_row)

	sku_filtered_data = []
	for row in data:
		if filters.get("sku_type"):
			sku_type_filter = filters.get("sku_type")
			sku_type_list = []
			if isinstance(sku_type_filter, str):
				if sku_type_filter.strip().startswith("[") or sku_type_filter.strip().startswith("{"):
					try:
						import json

						parsed = json.loads(sku_type_filter)
						if isinstance(parsed, list):
							sku_type_list = [str(s).strip() for s in parsed if s]
						else:
							sku_type_list = [str(parsed).strip()] if parsed else []
					except:
						# If JSON parsing fails, treat as comma-separated string
						sku_type_list = [s.strip() for s in sku_type_filter.split(",") if s.strip()]
				else:
					# Comma-separated string
					sku_type_list = [s.strip() for s in sku_type_filter.split(",") if s.strip()]
			elif isinstance(sku_type_filter, list):
				# Already a list
				sku_type_list = [str(s).strip() for s in sku_type_filter if s]
			else:
				# Single value
				sku_type_list = [str(sku_type_filter).strip()] if sku_type_filter else []

			# Only filter if we have valid SKU types in the filter
			if sku_type_list and row.get("sku_type") not in sku_type_list:
				continue

		sku_filtered_data.append(row)

	def get_on_hand_status_value(row):
		on_hand_status = row.get("on_hand_status")
		if on_hand_status is None:
			return float("inf")  # Put None values at the end
		try:
			numeric_value = float(on_hand_status.replace("%", "").strip())
			return numeric_value
		except (ValueError, AttributeError):
			return float("inf")  # Put invalid values at the end

	sku_filtered_data.sort(key=get_on_hand_status_value)
	remaining_child_stock_fifo = {}
	remaining_child_wip_open_po_fifo = {}

	for row in sku_filtered_data:
		child_item_code = row.get("child_item_code")
		if child_item_code:
			if child_item_code not in remaining_child_stock_fifo:
				if child_item_code in child_stock_map:
					remaining_child_stock_fifo[child_item_code] = child_stock_map[child_item_code]
				else:
					try:
						stock_data = frappe.db.sql(
							"""
							SELECT SUM(actual_qty) as stock
							FROM `tabBin`
							WHERE item_code = %s
							""",
							(child_item_code,),
							as_dict=True,
						)
						total_stock = int(
							flt(stock_data[0].stock if stock_data and stock_data[0].stock else 0)
						)
						child_stock_map[child_item_code] = total_stock
						remaining_child_stock_fifo[child_item_code] = total_stock
					except Exception:
						remaining_child_stock_fifo[child_item_code] = 0

			if child_item_code not in remaining_child_wip_open_po_fifo:
				if child_item_code in child_wip_open_po_map:
					remaining_child_wip_open_po_fifo[child_item_code] = flt(
						child_wip_open_po_map[child_item_code]
					)
				else:
					child_wip = flt(wip_map.get(child_item_code, 0))
					child_open_po = flt(open_po_map.get(child_item_code, 0))
					total_wip_open_po = flt(child_wip) + flt(child_open_po)
					child_wip_open_po_map[child_item_code] = total_wip_open_po
					remaining_child_wip_open_po_fifo[child_item_code] = total_wip_open_po

			child_requirement = flt(row.get("child_requirement", 0))
			available_stock = flt(remaining_child_stock_fifo.get(child_item_code, 0))
			stock_allocated = min(child_requirement, available_stock)
			stock_shortage = child_requirement - stock_allocated

			remaining_child_stock_fifo[child_item_code] = available_stock - stock_allocated

			remaining_requirement_after_stock = stock_shortage
			available_wip_open_po = flt(remaining_child_wip_open_po_fifo.get(child_item_code, 0))
			wip_open_po_allocated = min(remaining_requirement_after_stock, available_wip_open_po)
			wip_open_po_shortage = remaining_requirement_after_stock - wip_open_po_allocated

			remaining_child_wip_open_po_fifo[child_item_code] = available_wip_open_po - wip_open_po_allocated

			row["child_stock_soft_allocation_qty"] = math.ceil(stock_allocated)
			row["child_stock_shortage"] = math.ceil(stock_shortage)
			row["child_wip_open_po_soft_allocation_qty"] = math.ceil(wip_open_po_allocated)
			row["child_wip_open_po_shortage"] = math.ceil(wip_open_po_shortage)

			child_bom_qty = flt(row.get("child_bom_qty", 0))
			child_bom_quantity = flt(row.get("child_bom_quantity", 1.0)) or 1.0

			if child_bom_qty > 0:
				parent_per_child_factor = child_bom_quantity / child_bom_qty
			else:
				frappe.log_error(
					f"Missing BOM data for child {child_item_code} in parent {row.get('item_code')}. "
					f"Cannot calculate production qty.",
					"PO Recommendation - Missing BOM Data",
				)
				parent_per_child_factor = 0

			production_qty_based_on_child_stock = math.ceil(flt(stock_allocated) * parent_per_child_factor)
			row["production_qty_based_on_child_stock"] = production_qty_based_on_child_stock

			total_allocated = flt(stock_allocated) + flt(wip_open_po_allocated)
			production_qty_based_on_child_stock_wip_open_po = math.ceil(
				total_allocated * parent_per_child_factor
			)
			row["production_qty_based_on_child_stock_wip_open_po"] = (
				production_qty_based_on_child_stock_wip_open_po
			)

			net_order_recommendation = flt(row.get("or_with_moq_batch_size", 0))
			order_recommendation = flt(row.get("order_recommendation", 0))
			production_qty_stock_wip = flt(row.get("production_qty_based_on_child_stock_wip_open_po", 0))

			if flt(net_order_recommendation) == 0:
				row["child_wip_open_po_full_kit_status"] = None
			elif production_qty_stock_wip == 0:
				row["child_wip_open_po_full_kit_status"] = "Pending"
			elif production_qty_stock_wip >= net_order_recommendation:
				row["child_wip_open_po_full_kit_status"] = "Full-kit"
			else:
				row["child_wip_open_po_full_kit_status"] = "Partial"

			if flt(order_recommendation) == 0:
				row["child_full_kit_status"] = None
			elif flt(stock_shortage) == 0:
				row["child_full_kit_status"] = "Full-kit"
			elif flt(stock_allocated) == 0:
				row["child_full_kit_status"] = "Pending"
			else:
				row["child_full_kit_status"] = "Partial"

	parent_minimums = {}
	for row in sku_filtered_data:
		parent_item_code = row.get("item_code")
		child_item_code = row.get("child_item_code")
		if parent_item_code and child_item_code:
			if parent_item_code not in parent_minimums:
				parent_minimums[parent_item_code] = {
					"min_stock": None,
					"min_stock_wip": None,
				}

			production_qty_stock = flt(row.get("production_qty_based_on_child_stock", 0))
			production_qty_stock_wip = flt(row.get("production_qty_based_on_child_stock_wip_open_po", 0))

			if parent_minimums[parent_item_code]["min_stock"] is None:
				parent_minimums[parent_item_code]["min_stock"] = production_qty_stock
			else:
				parent_minimums[parent_item_code]["min_stock"] = min(
					parent_minimums[parent_item_code]["min_stock"], production_qty_stock
				)

			if parent_minimums[parent_item_code]["min_stock_wip"] is None:
				parent_minimums[parent_item_code]["min_stock_wip"] = production_qty_stock_wip
			else:
				parent_minimums[parent_item_code]["min_stock_wip"] = min(
					parent_minimums[parent_item_code]["min_stock_wip"], production_qty_stock_wip
				)

	for row in sku_filtered_data:
		parent_item_code = row.get("item_code")
		child_item_code = row.get("child_item_code")
		if parent_item_code and child_item_code and parent_item_code in parent_minimums:
			row["minimum_qty_based_on_child_stock"] = math.ceil(
				parent_minimums[parent_item_code]["min_stock"] or 0
			)
			row["minimum_qty_based_on_child_stock_wip_open_po"] = math.ceil(
				parent_minimums[parent_item_code]["min_stock_wip"] or 0
			)
		else:
			row["minimum_qty_based_on_child_stock"] = None
			row["minimum_qty_based_on_child_stock_wip_open_po"] = None

	filtered_data = []
	for row in sku_filtered_data:
		if filters.get("item_code"):
			if row.get("item_code") != filters.get("item_code"):
				continue
		filtered_data.append(row)

	parent_sequence_counts = {}
	for row in filtered_data:
		parent_item_code = row.get("item_code")
		if not parent_item_code:
			row["sequence"] = None
			continue
		current = parent_sequence_counts.get(parent_item_code, 0) + 1
		parent_sequence_counts[parent_item_code] = current
		row["sequence"] = f"{current:03d}"

	return filtered_data


@frappe.whitelist()
def create_material_request(item_code, qty):
	"""Create and submit a Material Request for the given item_code and quantity"""
	if not item_code:
		return {"error": "Item code is required"}

	if not qty or flt(qty) <= 0:
		return {"error": "Quantity must be greater than 0"}

	# Get item details
	if not frappe.db.exists("Item", item_code):
		return {"error": f"Item {item_code} not found"}

	item_doc = frappe.get_doc("Item", item_code)

	# Get UOM from item
	uom = item_doc.get("uom")
	if not uom:
		# If uom is not set, use stock_uom
		uom = item_doc.get("stock_uom")

	if not uom:
		return {"error": f"UOM not found for item {item_code}"}

	# Get stock_uom from item
	stock_uom = item_doc.get("stock_uom")
	if not stock_uom:
		return {"error": f"Stock UOM not found for item {item_code}"}

	# Get UOM conversion factor from item
	conversion_factor = 1.0
	if uom != stock_uom:
		# Try to get conversion factor from UOM Conversion Detail child table
		for uom_detail in item_doc.get("uoms", []):
			if uom_detail.uom == uom:
				conversion_factor = flt(uom_detail.conversion_factor)
				break

		# If not found in child table, check if item has uom_conversion_factor field
		if conversion_factor == 1.0 and hasattr(item_doc, "uom_conversion_factor"):
			conversion_factor = flt(item_doc.get("uom_conversion_factor", 1.0))

	# Calculate schedule_date (7 days from now)
	from frappe.utils import add_days, today

	schedule_date = add_days(today(), 7)

	# Set company name
	company = "Prakash Steel Products Pvt Ltd"

	# Verify company exists
	if not frappe.db.exists("Company", company):
		return {"error": f"Company '{company}' not found in the system."}

	try:
		# Set warehouse
		warehouse = "Bright Bar Unit - PSPL"

		# Verify warehouse exists
		if not frappe.db.exists("Warehouse", warehouse):
			return {"error": f"Warehouse '{warehouse}' not found in the system."}

		# Create Material Request
		mr_doc = frappe.get_doc(
			{
				"doctype": "Material Request",
				"company": company,
				"transaction_date": today(),
				"schedule_date": schedule_date,
				"material_request_type": "Purchase",
				"items": [
					{
						"item_code": item_code,
						"qty": flt(qty),
						"uom": uom,
						"stock_uom": stock_uom,
						"conversion_factor": conversion_factor,
						"warehouse": warehouse,
					}
				],
			}
		)

		mr_doc.insert()
		mr_doc.submit()

		return {
			"material_request": mr_doc.name,
			"message": f"Material Request {mr_doc.name} created and submitted successfully",
		}
	except Exception as e:
		frappe.log_error(f"Error creating Material Request: {str(e)}", "Create Material Request Error")
		return {"error": f"Error creating Material Request: {str(e)}"}


@frappe.whitelist()
def create_material_requests_automatically(filters=None):
	"""Create Material Requests automatically for all items with net_po_recommendation > 0"""
	# Parse filters if it's a JSON string
	if isinstance(filters, str):
		import json

		try:
			filters = json.loads(filters)
		except:
			filters = {}

	if not filters:
		filters = {}

	# Get report data
	_, data = execute(filters)

	if not data:
		return {
			"success_count": 0,
			"error_count": 0,
			"material_requests": [],
			"message": "No data found in report",
		}

	# Filter items with net_po_recommendation > 0
	items_to_process = [
		row
		for row in data
		if row.get("net_po_recommendation") and flt(row.get("net_po_recommendation", 0)) > 0
	]

	if not items_to_process:
		return {
			"success_count": 0,
			"error_count": 0,
			"material_requests": [],
			"message": "No items with Net PO Recommendation > 0 found",
		}

	success_count = 0
	error_count = 0
	material_requests = []
	errors = []

	# Create Material Request for each item
	for row in items_to_process:
		item_code = row.get("item_code")
		qty = flt(row.get("net_po_recommendation", 0))

		if not item_code or qty <= 0:
			error_count += 1
			errors.append(f"{item_code}: Invalid quantity")
			continue

		try:
			result = create_material_request(item_code, qty)
			if result.get("error"):
				error_count += 1
				errors.append(f"{item_code}: {result.get('error')}")
			else:
				success_count += 1
				material_requests.append(result.get("material_request"))
		except Exception as e:
			error_count += 1
			errors.append(f"{item_code}: {str(e)}")
			frappe.log_error(
				f"Error creating Material Request for {item_code}: {str(e)}",
				"Create Material Requests Automatically Error",
			)

	return {
		"success_count": success_count,
		"error_count": error_count,
		"material_requests": material_requests,
		"errors": errors[:10] if len(errors) > 10 else errors,  # Limit errors to first 10
		"message": f"Created {success_count} Material Request(s), {error_count} failed",
	}


def get_stock_map(item_codes):
	"""Get stock map for all items"""
	if not item_codes:
		return {}

	if len(item_codes) == 1:
		item_codes_tuple = (next(iter(item_codes)),)
	else:
		item_codes_tuple = tuple(item_codes)

	bin_rows = frappe.db.sql(
		"""
		SELECT item_code, SUM(actual_qty) as stock
		FROM `tabBin`
		WHERE item_code IN %s
		GROUP BY item_code
		""",
		(item_codes_tuple,),
		as_dict=True,
	)

	return {d.item_code: flt(d.stock) for d in bin_rows}


def get_sales_order_qty_map(filters):
	"""Get sales order qty map for all items"""
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
		GROUP BY
			soi.item_code
		""",
		as_dict=True,
	)

	return {d.item_code: flt(d.so_qty) for d in so_rows}


def get_qualified_demand_map(filters):
	"""Get qualified demand map for all items"""
	from frappe.utils import today

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


def get_wip_map(filters):
	"""Get WIP map based on Production Plan Settings"""
	try:
		settings = frappe.get_single("Production planning settings")
	except Exception:
		settings = frappe._dict({"from_work_order": 1, "from_production_plan": 0})

	wip_map = {}

	if settings.get("from_work_order"):
		wip_rows_wo = frappe.db.sql(
			"""
			SELECT
				wo.production_item as item_code,
				SUM(GREATEST(0, IFNULL(wo.qty, 0) - IFNULL(wo.produced_qty, 0))) as wip_qty
			FROM
				`tabWork Order` wo
			WHERE
				wo.status NOT IN ('Completed', 'Cancelled')
				AND wo.docstatus = 1
			GROUP BY
				wo.production_item
			""",
			as_dict=True,
		)

		for row in wip_rows_wo:
			item_code = row.item_code
			wip_map[item_code] = flt(row.wip_qty)

	elif settings.get("from_production_plan"):
		production_plans = frappe.get_all("Production Plan", filters={"docstatus": 1}, fields=["name"])

		for pp in production_plans:
			pp_name = pp.name

			try:
				pp_doc = frappe.get_doc("Production Plan", pp_name)

				if hasattr(pp_doc, "po_items") and pp_doc.po_items:
					for po_item in pp_doc.po_items:
						item_code = po_item.item_code
						planned_qty = flt(po_item.planned_qty) if po_item.planned_qty else 0

						if not item_code:
							continue

						finished_weight_docs = frappe.db.sql(
							"""
							SELECT name, finish_weight
							FROM `tabFinish Weight`
							WHERE production_plan = %s
							AND docstatus = 1
							AND item_code = %s
							ORDER BY name
							""",
							(pp_name, item_code),
							as_dict=True,
						)

						total_finished_from_fw = sum(flt(doc.finish_weight) for doc in finished_weight_docs)
						bright_bar_production_docs = frappe.db.sql(
							"""
							SELECT name, fg_weight
							FROM `tabBright Bar Production`
							WHERE production_plan = %s
							AND docstatus = 1
							AND finished_good = %s
							ORDER BY name
							""",
							(pp_name, item_code),
							as_dict=True,
						)

						total_finished_from_bbp = sum(
							flt(doc.fg_weight) for doc in bright_bar_production_docs
						)
						total_finished = total_finished_from_fw + total_finished_from_bbp
						wip_qty = max(0, planned_qty - total_finished)

						if item_code in wip_map:
							wip_map[item_code] += wip_qty
						else:
							wip_map[item_code] = wip_qty

			except Exception as e:
				frappe.log_error(
					f"Error processing Production Plan {pp_name} in get_wip_map: {str(e)}",
					"PO Recommendation WIP Calculation Error",
				)
				continue

	return wip_map


def get_mrq_map(filters):
	"""Get MRQ map for all items"""
	# Get Material Requests with status 'Pending' or 'Partially Ordered'
	mrq_rows = frappe.db.sql(
		"""
		SELECT
			mri.item_code,
			SUM(GREATEST(0, mri.qty - IFNULL(mri.ordered_qty, 0))) as mrq_qty
		FROM
			`tabMaterial Request` mr
		INNER JOIN
			`tabMaterial Request Item` mri ON mri.parent = mr.name
		WHERE
			mr.docstatus = 1
			AND mr.status IN ('Pending', 'Partially Ordered')
		GROUP BY
			mri.item_code
		""",
		as_dict=True,
	)

	return {d.item_code: flt(d.mrq_qty) for d in mrq_rows}


def get_open_po_map():
	"""Get Open PO map for all items"""
	po_rows = frappe.db.sql(
		"""
		SELECT
			poi.item_code,
			poi.qty,
			IFNULL(poi.received_qty, 0) as received_qty
		FROM
			`tabPurchase Order` po
		INNER JOIN
			`tabPurchase Order Item` poi ON poi.parent = po.name
		WHERE
			po.docstatus = 1
			AND po.status NOT IN ('Cancelled', 'Closed')
		""",
		as_dict=True,
	)

	open_po_map = {}
	for row in po_rows:
		item_code = row.item_code
		qty = flt(row.qty)
		received_qty = flt(row.received_qty)
		open_qty = max(0, qty - received_qty)

		if item_code in open_po_map:
			open_po_map[item_code] += open_qty
		else:
			open_po_map[item_code] = open_qty

	# Get Subcontracting Order items for Purchase Orders with is_subcontracted = 1
	subcontracting_rows = frappe.db.sql(
		"""
		SELECT
			scoi.item_code,
			scoi.qty,
			IFNULL(scoi.received_qty, 0) as received_qty
		FROM
			`tabPurchase Order` po
		INNER JOIN
			`tabSubcontracting Order` sco ON sco.purchase_order = po.name
		INNER JOIN
			`tabSubcontracting Order Item` scoi ON scoi.parent = sco.name
		WHERE
			po.docstatus = 1
			AND po.status NOT IN ('Cancelled', 'Closed')
			AND po.is_subcontracted = 1
			AND scoi.parentfield = 'items'
		""",
		as_dict=True,
	)

	# Add subcontracting order quantities to open_po_map
	for row in subcontracting_rows:
		item_code = row.item_code
		qty = flt(row.qty)
		received_qty = flt(row.received_qty)
		open_qty = max(0, qty - received_qty)

		if item_code in open_po_map:
			open_po_map[item_code] += open_qty
		else:
			open_po_map[item_code] = open_qty

	return open_po_map


def traverse_bom_for_parent_demand_simple(
	parent_item_code,
	parent_net_order_qty,
	parent_demand_map,
	visited_items,
	item_groups_cache,
	item_buffer_map,
	level=0,
):
	"""Simple BOM traversal for first pass - accumulates parent demands"""
	if parent_item_code in visited_items:
		return

	visited_items.add(parent_item_code)

	item_group = item_groups_cache.get(parent_item_code)
	if not item_group:
		try:
			item_doc = frappe.get_doc("Item", parent_item_code)
			item_group = item_doc.get("item_group")
			item_groups_cache[parent_item_code] = item_group
		except:
			item_group = None

	if item_group == "Raw Material":
		return

	bom = get_default_bom(parent_item_code)
	if not bom:
		return

	try:
		bom_doc = frappe.get_doc("BOM", bom)
		bom_quantity = flt(bom_doc.quantity)
		if bom_quantity <= 0:
			bom_quantity = 1.0

		for bom_item in bom_doc.items:
			child_item_code = bom_item.item_code
			bom_item_qty = flt(bom_item.qty)

			normalized_bom_qty = bom_item_qty / bom_quantity
			child_required_qty = parent_net_order_qty * normalized_bom_qty

			child_buffer_flag = item_buffer_map.get(child_item_code, "Non-Buffer")
			is_child_buffer = child_buffer_flag == "Buffer"

			if not is_child_buffer:
				if child_item_code in parent_demand_map:
					parent_demand_map[child_item_code] += child_required_qty
				else:
					parent_demand_map[child_item_code] = child_required_qty
			if child_item_code not in visited_items:
				traverse_bom_for_parent_demand_simple(
					child_item_code,
					child_required_qty,
					parent_demand_map,
					visited_items.copy(),
					item_groups_cache,
					item_buffer_map,
					level + 1,
				)
	except Exception as e:
		frappe.log_error(f"Error traversing BOM for {parent_item_code}: {str(e)}", "PO Recommendation Error")


def traverse_bom_for_parent_demand(
	parent_item_code,
	parent_net_order_qty,
	parent_demand_map,
	visited_items,
	item_groups_cache,
	open_so_map,
	stock_map,
	wip_map,
	open_po_map,
	mrq_map,
	moq_map,
	batch_size_map,
	item_buffer_map,
	item_sku_type_map,
	get_item_details_func,
	level=0,
):
	"""Recursively traverse BOM using net_order_recommendations"""
	if parent_item_code in visited_items:
		return

	visited_items.add(parent_item_code)

	item_group = item_groups_cache.get(parent_item_code)
	if not item_group:
		try:
			item_doc = frappe.get_doc("Item", parent_item_code)
			item_group = item_doc.get("item_group")
			item_groups_cache[parent_item_code] = item_group
		except:
			item_group = None

	if item_group == "Raw Material":
		return

	bom = get_default_bom(parent_item_code)
	if not bom:
		return

	try:
		bom_doc = frappe.get_doc("BOM", bom)
		bom_quantity = flt(bom_doc.quantity)
		if bom_quantity <= 0:
			bom_quantity = 1.0

		for bom_item in bom_doc.items:
			child_item_code = bom_item.item_code
			bom_item_qty = flt(bom_item.qty)

			normalized_bom_qty = bom_item_qty / bom_quantity
			child_required_qty = parent_net_order_qty * normalized_bom_qty

			get_item_details_func(child_item_code)
			child_buffer_flag = item_buffer_map.get(child_item_code, "Non-Buffer")
			is_child_buffer = child_buffer_flag == "Buffer"

			if not is_child_buffer:
				if child_item_code in parent_demand_map:
					parent_demand_map[child_item_code] += child_required_qty
				else:
					parent_demand_map[child_item_code] = child_required_qty

				child_qualified_demand = flt(open_so_map.get(child_item_code, 0))
				child_parent_demand = flt(parent_demand_map.get(child_item_code, 0))
				child_requirement = child_qualified_demand + child_parent_demand
				child_stock = flt(stock_map.get(child_item_code, 0))
				child_wip = flt(wip_map.get(child_item_code, 0))
				child_sku_type = item_sku_type_map.get(child_item_code)
				child_open_po = flt(open_po_map.get(child_item_code, 0))
				child_mrq = flt(mrq_map.get(child_item_code, 0))

				if child_sku_type in ["PTO", "BOTO"]:
					base_child_order_rec = child_requirement - child_stock - child_wip - child_open_po
				else:
					base_child_order_rec = child_requirement - child_stock - child_wip

				child_base_order_rec = max(0, base_child_order_rec - child_mrq)

				child_moq = flt(moq_map.get(child_item_code, 0))
				child_batch_size = flt(batch_size_map.get(child_item_code, 0))
				child_net_order_rec = calculate_net_order_recommendation(
					child_base_order_rec, child_moq, child_batch_size
				)

				if child_net_order_rec > 0 and child_item_code not in visited_items:
					traverse_bom_for_parent_demand(
						child_item_code,
						child_net_order_rec,
						parent_demand_map,
						visited_items.copy(),
						item_groups_cache,
						open_so_map,
						stock_map,
						wip_map,
						open_po_map,
						mrq_map,
						moq_map,
						batch_size_map,
						item_buffer_map,
						item_sku_type_map,
						get_item_details_func,
						level + 1,
					)

	except Exception as e:
		frappe.log_error(
			f"Error traversing BOM for parent demand for item {parent_item_code}: {str(e)}",
			"PO Recommendation Error",
		)


def traverse_bom_for_po(
	item_code, required_qty, po_recommendations, remaining_stock, visited_items, item_groups_cache, level=0
):
	"""Recursively traverse BOM to calculate PO recommendations for child items"""
	if item_code in visited_items:
		return

	visited_items.add(item_code)

	item_group = item_groups_cache.get(item_code)
	if not item_group:
		try:
			item_doc = frappe.get_doc("Item", item_code)
			item_group = item_doc.get("item_group")
			item_groups_cache[item_code] = item_group
		except:
			item_group = None

	if item_group == "Raw Material":
		return

	bom = get_default_bom(item_code)
	if not bom:
		return

	try:
		bom_doc = frappe.get_doc("BOM", bom)

		for bom_item in bom_doc.items:
			child_item_code = bom_item.item_code
			bom_qty = flt(bom_item.qty)
			child_required_qty = required_qty * bom_qty
			child_available_stock = flt(remaining_stock.get(child_item_code, 0))

			if child_item_code not in remaining_stock:
				stock_data = frappe.db.sql(
					"""
					SELECT SUM(actual_qty) as stock
					FROM `tabBin`
					WHERE item_code = %s
					""",
					(child_item_code,),
					as_dict=True,
				)
				child_available_stock = flt(stock_data[0].stock if stock_data else 0)
				remaining_stock[child_item_code] = child_available_stock

			allocated = min(child_required_qty, child_available_stock)
			remaining_stock[child_item_code] = child_available_stock - allocated
			child_po = max(0, child_required_qty - allocated)

			if child_item_code in po_recommendations:
				po_recommendations[child_item_code] += child_po
			else:
				po_recommendations[child_item_code] = child_po

			if child_po > 0:
				traverse_bom_for_po(
					child_item_code,
					child_po,
					po_recommendations,
					remaining_stock,
					visited_items.copy(),
					item_groups_cache,
					level + 1,
				)

	except Exception as e:
		frappe.log_error(f"Error traversing BOM for item {item_code}: {str(e)}", "PO Recommendation Error")

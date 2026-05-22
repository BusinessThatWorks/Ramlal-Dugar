# Copyright (c) 2025, beetashoke chakraborty and contributors
# For license information, please see license.txt

import frappe


def calculate_decoupled_lead_time(item_code):
	if not item_code:
		return 0

	# Check if item exists in database before trying to calculate
	# This prevents errors when calculating for new items that haven't been saved yet
	if not frappe.db.exists("Item", item_code):
		return 0

	# Track visited items to avoid infinite loops
	visited_items = set()

	# Cache for item_group lookups to improve performance
	item_groups_cache = {}

	# Calculate recursively
	try:
		result = _calculate_lead_time_recursive(item_code, visited_items, item_groups_cache)
		return result
	except frappe.DoesNotExistError:
		# Item doesn't exist (might have been deleted), return 0 silently
		return 0
	except Exception as e:
		frappe.log_error(
			f"Error in calculate_decoupled_lead_time for item {item_code}: {str(e)}\nTraceback: {frappe.get_traceback()}",
			"Lead Time Calculation Error",
		)
		return 0


def _calculate_lead_time_recursive(item_code, visited_items, item_groups_cache=None):
	if not item_code or item_code in visited_items:
		return 0

	# Mark as visited
	visited_items.add(item_code)

	# Initialize cache if not provided
	if item_groups_cache is None:
		item_groups_cache = {}

	try:
		# Get the item document
		item_doc = frappe.get_doc("Item", item_code)

		# Get item's own lead time (regardless of buffer status)
		item_lead_time = flt(item_doc.get("lead_time_days") or 0)

		# OPTIMIZATION: Check item_group first - Raw Materials don't have BOMs
		# This avoids unnecessary BOM lookup for raw materials
		item_group = item_doc.get("item_group")

		# Cache the item_group for future use
		if item_code not in item_groups_cache:
			item_groups_cache[item_code] = item_group

		# If it's a Raw Material, skip BOM check (end of branch)
		if item_group == "Raw Material":
			return item_lead_time

		# Get default BOM for this item (only if not Raw Material)
		bom = get_default_bom(item_code)

		# If no BOM, return only item's own lead time (end of branch)
		if not bom:
			return item_lead_time

		# Get BOM document
		try:
			bom_doc = frappe.get_doc("BOM", bom)
		except Exception as e:
			frappe.log_error(
				f"Error getting BOM {bom} for item {item_code}: {str(e)}", "Lead Time Calculation Error"
			)
			return item_lead_time

		# Process ALL BOM items (both buffer and non-buffer)
		# For each child item, calculate its contribution to the longest path
		child_contributions = []

		for bom_item in bom_doc.items:
			child_item_code = bom_item.item_code

			# Skip if already visited (circular reference protection)
			if child_item_code in visited_items:
				continue

			try:
				# OPTIMIZATION: Check item_group from cache first
				child_item_group = item_groups_cache.get(child_item_code)

				# If it's Raw Material (from cache), get lead time but skip BOM check
				if child_item_group == "Raw Material":
					# Raw Material - get lead time but don't check for BOM (end of branch)
					child_item = frappe.get_doc("Item", child_item_code)
					child_lead_time = flt(child_item.get("lead_time_days") or 0)
					# Raw Material contributes only its own lead time
					child_contributions.append(child_lead_time)
					continue

				# Get child item document
				child_item = frappe.get_doc("Item", child_item_code)

				# Cache item_group if not already cached
				if child_item_code not in item_groups_cache:
					item_groups_cache[child_item_code] = child_item.get("item_group")

				# Get child item's own lead time
				child_lead_time = flt(child_item.get("lead_time_days") or 0)

				# Check if child is buffer
				child_buffer_flag = child_item.get("custom_buffer_flag")
				child_is_buffer = child_buffer_flag == "Buffer"

				if child_is_buffer:
					# Buffer item: stop the path here, contribute 0 (don't traverse its BOM)
					# The path ends at the buffer item, so it contributes nothing to parent
					child_contributions.append(0)
				else:
					# Non-buffer item: recursively get its full decoupled_lead_time
					# Create a copy of visited_items for this branch
					branch_visited = visited_items.copy()

					# Recursively calculate FULL decoupled lead time for this child
					child_full_decoupled = _calculate_lead_time_recursive(
						child_item_code, branch_visited, item_groups_cache
					)

					# The child's full decoupled includes its own lead_time + BOM contribution
					# We need the full value for the path calculation
					child_contributions.append(child_full_decoupled)

			except frappe.DoesNotExistError:
				# Child item doesn't exist, skip it
				continue
			except Exception as e:
				frappe.log_error(
					f"Error processing child item {child_item_code} in BOM {bom}: {str(e)}",
					"Lead Time Calculation Error",
				)
				continue

		# If no valid child items, return only item's own lead time
		if not child_contributions:
			return item_lead_time

		# Take the maximum contribution from all children (longest path)
		max_child_contribution = max(child_contributions)

		# Return: item's own lead time + longest path through BOM
		result = item_lead_time + max_child_contribution
		return result

	except frappe.DoesNotExistError:
		# Item doesn't exist
		frappe.log_error(f"Item {item_code} does not exist", "Lead Time Calculation Error")
		return 0
	except Exception as e:
		frappe.log_error(
			f"Error calculating lead time for item {item_code}: {str(e)}\nTraceback: {frappe.get_traceback()}",
			"Lead Time Calculation Error",
		)
		return 0


def get_default_bom(item_code):
	"""
	Get the default BOM for an item.

	Args:
		item_code (str): Item code

	Returns:
		str: BOM name if found, None otherwise
	"""
	# First try to get default active BOM (submitted)
	bom = frappe.db.get_value(
		"BOM",
		{"item": item_code, "is_active": 1, "is_default": 1, "docstatus": 1},
		"name",
		order_by="creation desc",
	)

	# If no default submitted BOM, try any active submitted BOM
	if not bom:
		bom = frappe.db.get_value(
			"BOM", {"item": item_code, "is_active": 1, "docstatus": 1}, "name", order_by="creation desc"
		)

	# If still no BOM, try any active BOM (even if not submitted)
	if not bom:
		bom = frappe.db.get_value(
			"BOM", {"item": item_code, "is_active": 1}, "name", order_by="creation desc"
		)

	return bom


def update_decoupled_lead_time_for_item(item_code):
	"""
	Update the decoupled lead time field for a specific item.
	Args:
		item_code (str): Item code to update
	"""
	try:
		# Safety check: Verify Item exists and is not submitted (Item should never be submitted)
		item_docstatus = frappe.db.get_value("Item", item_code, "docstatus")
		if item_docstatus is None:
			# Item doesn't exist
			return None

		# Item should always have docstatus = 0 (it's a save doctype, not submit doctype)
		# If somehow it's submitted, log a warning but still update the field
		if item_docstatus != 0:
			frappe.log_error(
				f"WARNING: Item {item_code} has docstatus={item_docstatus} (expected 0). Item should not be submitted.",
				"Item Docstatus Warning",
			)

		decoupled_lead_time = calculate_decoupled_lead_time(item_code)

		# Use frappe.db.set_value() to update only the field value
		# This does NOT submit the document, it only updates the field
		frappe.db.set_value("Item", item_code, "custom_decoupled_lead_time", decoupled_lead_time)

		return decoupled_lead_time
	except Exception as e:
		frappe.log_error(
			f"Error updating decoupled lead time for item {item_code}: {str(e)}",
			"Decoupled Lead Time Update Error",
		)
		return None


def update_decoupled_lead_time_for_finished_goods():
	"""
	Update decoupled lead time for all finished goods items that have BOMs.
	"""
	# Get all items that have active BOMs
	items_with_bom = frappe.db.sql(
		"""
		SELECT DISTINCT b.item
		FROM `tabBOM` b
		WHERE b.is_active = 1
		AND b.docstatus = 1
	""",
		as_dict=True,
	)

	updated_count = 0
	for item in items_with_bom:
		item_code = item.item
		if update_decoupled_lead_time_for_item(item_code):
			updated_count += 1

	frappe.msgprint(f"Updated decoupled lead time for {updated_count} items")
	return updated_count


def flt(value, precision=None):
	"""Wrapper for frappe.utils.flt"""
	from frappe.utils import flt as _flt

	return _flt(value, precision)


@frappe.whitelist()
def debug_lead_time_calculation(item_code):
	"""
	Debug function to help diagnose lead time calculation issues with detailed breakdown.

	Args:
		item_code (str): Item code to debug

	Returns:
		dict: Debug information about the item and its lead time calculation
	"""
	if not item_code:
		return {"error": "Item code is required"}

	# Check if item exists in database (not a new item being created)
	if not frappe.db.exists("Item", item_code):
		return {
			"error": f"Item {item_code} not found. Item may not be saved yet (new item).",
			"item_code": item_code,
		}

	try:
		item_doc = frappe.get_doc("Item", item_code)

		# Calculate with detailed trace
		visited_items = set()
		item_groups_cache = {}
		calculation_trace = []
		calculated_value = _calculate_lead_time_recursive_with_trace(
			item_code, visited_items, calculation_trace, level=0, item_groups_cache=item_groups_cache
		)

		debug_info = {
			"item_code": item_code,
			"lead_time_days": item_doc.get("lead_time_days"),
			"custom_buffer_flag": item_doc.get("custom_buffer_flag"),
			"is_buffer": item_doc.get("custom_buffer_flag") == "Buffer",
			"has_bom": False,
			"bom_name": None,
			"calculated_decoupled_lead_time": calculated_value,
			"calculation_trace": calculation_trace,
		}

		# Check for BOM
		bom = get_default_bom(item_code)
		if bom:
			debug_info["has_bom"] = True
			debug_info["bom_name"] = bom

			# Get BOM items info
			bom_doc = frappe.get_doc("BOM", bom)
			bom_items_info = []
			for bom_item in bom_doc.items:
				try:
					child_item = frappe.get_doc("Item", bom_item.item_code)
					bom_items_info.append(
						{
							"item_code": bom_item.item_code,
							"lead_time_days": child_item.get("lead_time_days"),
							"custom_buffer_flag": child_item.get("custom_buffer_flag"),
							"is_buffer": child_item.get("custom_buffer_flag") == "Buffer",
						}
					)
				except Exception as e:
					bom_items_info.append({"item_code": bom_item.item_code, "error": str(e)})
			debug_info["bom_items"] = bom_items_info

		return debug_info

	except Exception as e:
		return {"error": str(e), "traceback": frappe.get_traceback()}


def _calculate_lead_time_recursive_with_trace(
	item_code, visited_items, trace, level=0, item_groups_cache=None
):
	"""
	Recursive helper with detailed trace for debugging.

	Args:
		item_code (str): Item code
		visited_items (set): Set of visited item codes
		trace (list): List to store calculation trace
		level (int): Current recursion level
		item_groups_cache (dict): Cache for item_group lookups

	Returns:
		float: Decoupled lead time
	"""
	if not item_code or item_code in visited_items:
		return 0

	# Mark as visited
	visited_items.add(item_code)

	# Initialize cache if not provided
	if item_groups_cache is None:
		item_groups_cache = {}

	indent = "  " * level
	trace_entry = {
		"level": level,
		"item_code": item_code,
		"own_lead_time": None,
		"is_buffer": False,
		"has_bom": False,
		"bom_items": [],
		"max_lead_time_at_level": None,
		"items_with_max": [],
		"recursive_contribution": None,
		"total": None,
	}

	try:
		# Get the item document
		item_doc = frappe.get_doc("Item", item_code)

		# Check if item is buffer
		custom_buffer_flag = item_doc.get("custom_buffer_flag")
		is_buffer = custom_buffer_flag == "Buffer"
		trace_entry["is_buffer"] = is_buffer

		# Get item's own lead time
		item_lead_time = flt(item_doc.get("lead_time_days") or 0)
		trace_entry["own_lead_time"] = item_lead_time

		# If buffer, return its own lead_time and don't traverse BOM
		if is_buffer:
			trace_entry["total"] = item_lead_time
			trace.append(trace_entry)
			return item_lead_time

		# OPTIMIZATION: Check item_group first - Raw Materials don't have BOMs
		item_group = item_doc.get("item_group")

		# Cache the item_group
		if item_code not in item_groups_cache:
			item_groups_cache[item_code] = item_group

		# If it's a Raw Material, skip BOM check (end of branch)
		if item_group == "Raw Material":
			trace_entry["total"] = item_lead_time
			trace.append(trace_entry)
			return item_lead_time

		# Get default BOM for this item (only if not Raw Material)
		bom = get_default_bom(item_code)

		# If no BOM, return only item's own lead time
		if not bom:
			trace_entry["total"] = item_lead_time
			trace.append(trace_entry)
			return item_lead_time

		trace_entry["has_bom"] = True
		trace_entry["bom_name"] = bom

		# Get BOM document
		try:
			bom_doc = frappe.get_doc("BOM", bom)
		except Exception as e:
			frappe.log_error(
				f"Error getting BOM {bom} for item {item_code}: {str(e)}", "Lead Time Calculation Error"
			)
			trace_entry["total"] = item_lead_time
			trace.append(trace_entry)
			return item_lead_time

		# Collect all non-buffer items with their lead times
		non_buffer_items = []

		for bom_item in bom_doc.items:
			child_item_code = bom_item.item_code

			# Skip if already visited (circular reference protection)
			if child_item_code in visited_items:
				continue

			try:
				# OPTIMIZATION: Check item_group from cache first
				child_item_group = item_groups_cache.get(child_item_code)

				# If Raw Material, get lead time but skip BOM check
				if child_item_group == "Raw Material":
					child_item = frappe.get_doc("Item", child_item_code)
					child_lead_time = flt(child_item.get("lead_time_days") or 0)

					# Cache item_group if not already cached
					if child_item_code not in item_groups_cache:
						item_groups_cache[child_item_code] = child_item.get("item_group")

					# Store info for trace
					bom_item_info = {
						"item_code": child_item_code,
						"lead_time": child_lead_time,
						"is_buffer": False,
						"is_raw_material": True,
					}
					trace_entry["bom_items"].append(bom_item_info)

					# Store as non-buffer item (Raw Materials are end of branch)
					non_buffer_items.append({"item_code": child_item_code, "lead_time": child_lead_time})
					continue

				# Get child item document (only if not Raw Material or not in cache)
				child_item = frappe.get_doc("Item", child_item_code)

				# Cache item_group if not already cached
				if child_item_code not in item_groups_cache:
					item_groups_cache[child_item_code] = child_item.get("item_group")

				# Check if child is buffer
				child_buffer_flag = child_item.get("custom_buffer_flag")
				child_is_buffer = child_buffer_flag == "Buffer"

				# Get child item's own lead time
				child_lead_time = flt(child_item.get("lead_time_days") or 0)

				# Store info for trace
				bom_item_info = {
					"item_code": child_item_code,
					"lead_time": child_lead_time,
					"is_buffer": child_is_buffer,
				}
				trace_entry["bom_items"].append(bom_item_info)

				# Skip buffer items in BOM calculation (they don't contribute to parent's decoupled_lead_time)
				# But buffer items themselves have decoupled_lead_time = their own lead_time
				if child_is_buffer:
					continue

				# Store non-buffer item info
				non_buffer_items.append({"item_code": child_item_code, "lead_time": child_lead_time})

			except frappe.DoesNotExistError:
				# Child item doesn't exist, skip it
				trace_entry["bom_items"].append(
					{"item_code": child_item_code, "error": "Item does not exist"}
				)
				continue
			except Exception as e:
				frappe.log_error(
					f"Error processing child item {child_item_code} in BOM {bom}: {str(e)}",
					"Lead Time Calculation Error",
				)
				trace_entry["bom_items"].append({"item_code": child_item_code, "error": str(e)})
				continue

		# If no non-buffer items at this level, return only item's own lead time
		if not non_buffer_items:
			trace_entry["total"] = item_lead_time
			trace.append(trace_entry)
			return item_lead_time

		# Find the maximum lead time among non-buffer items at this level
		max_lead_time = max(item["lead_time"] for item in non_buffer_items)
		trace_entry["max_lead_time_at_level"] = max_lead_time

		# Find all items with maximum lead time (there might be multiple)
		max_lead_time_items = [
			item["item_code"] for item in non_buffer_items if item["lead_time"] == max_lead_time
		]
		trace_entry["items_with_max"] = max_lead_time_items

		# Recursively process the BOM of item(s) with maximum lead time
		max_recursive_contribution = 0

		for max_item_code in max_lead_time_items:
			# Create a copy of visited_items for each branch
			branch_visited = visited_items.copy()

			# Recursively calculate FULL decoupled lead time for this item
			# Pass the cache to avoid redundant lookups
			child_full_decoupled = _calculate_lead_time_recursive_with_trace(
				max_item_code, branch_visited, trace, level + 1, item_groups_cache
			)

			# The child's full decoupled includes its own lead_time + BOM contribution
			# We've already added the child's own lead_time (max_lead_time) separately
			# So we need to subtract it to get only the BOM contribution
			child_bom_contribution = child_full_decoupled - max_lead_time

			# Take the maximum contribution from all branches
			max_recursive_contribution = max(max_recursive_contribution, child_bom_contribution)

		trace_entry["recursive_contribution"] = max_recursive_contribution
		# Return: item's own lead time + max lead time at this level + max from deeper levels
		result = item_lead_time + max_lead_time + max_recursive_contribution
		trace_entry["total"] = result
		trace.append(trace_entry)
		return result

	except frappe.DoesNotExistError:
		# Item doesn't exist
		frappe.log_error(f"Item {item_code} does not exist", "Lead Time Calculation Error")
		trace_entry["error"] = "Item does not exist"
		trace.append(trace_entry)
		return 0
	except Exception as e:
		frappe.log_error(
			f"Error calculating lead time for item {item_code}: {str(e)}\nTraceback: {frappe.get_traceback()}",
			"Lead Time Calculation Error",
		)
		trace_entry["error"] = str(e)
		trace.append(trace_entry)
		return 0

# Copyright (c) 2025, beetashoke chakraborty and contributors
# For license information, please see license.txt

import frappe
import math
from frappe.model.document import Document
from frappe.utils import flt
from prakash_steel.utils.lead_time import get_default_bom


class MRPGenaration(Document):
	pass


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


@frappe.whitelist()
def generate_mrp_order_recommendations():
	"""
	Enqueue MRP order recommendations calculation as a background job.
	Returns job_id for status polling.

	The job will be visible in:
	- RQ Job list (search "RQ Job" in Frappe)
	- System Health Report
	- Worker logs
	"""
	# Enqueue the worker function as a background job
	job = frappe.enqueue(
		"prakash_steel.prakash_steel.doctype.mrp_genaration.mrp_genaration._generate_mrp_order_recommendations_worker",
		queue="long",
		timeout=3600,  # 1 hour timeout
		job_name=f"MRP Generation - {frappe.session.user}",
		is_async=True,
		now=False,  # Ensure it's queued, not executed immediately
	)

	job_id = job.id if hasattr(job, "id") else str(job)

	# Store job_id in cache for later retrieval
	frappe.cache().set_value(f"mrp_job_id_{frappe.session.user}", job_id, expires_in_sec=3600)

	# Log job creation
	print(f"[MRP] Job queued with ID: {job_id}, Name: MRP Generation - {frappe.session.user}")
	frappe.log_error(f"MRP Generation job queued: {job_id}", "MRP Generation Job")

	return {
		"job_id": job_id,
		"status": "queued",
		"message": f"MRP calculation job has been queued (Job ID: {job_id}). Check 'RQ Job' list to monitor progress.",
	}


def _generate_mrp_order_recommendations_worker():
	"""
	Worker function that performs the actual MRP calculation.
	This runs as a background job to prevent UI blocking.

	Logic:
	- Buffer items: Order recommendation = TOG - Stock - WIP (parent demand ignored)
	- Non-buffer items: Order recommendation = max(0, Requirement - Stock - WIP)
	  where Requirement = Open SO + sum of all parent BOM demands
	- When traversing BOM:
	  - For buffer child items: Don't add parent demand, only use TOG-based calculation
	  - For non-buffer child items: Add parent demand to requirement
	"""
	# Log job start
	job_id = None
	try:
		job = frappe.get_job()
		if job and hasattr(job, "id"):
			job_id = job.id
	except:
		pass

	if not job_id:
		job_id = frappe.cache().get_value(f"mrp_job_id_{frappe.session.user}")

	start_msg = f"[MRP Job {job_id or 'Unknown'}] Starting MRP calculation..."
	print(start_msg)
	frappe.log_error(start_msg, "MRP Generation Job")

	# Get all items (buffer and non-buffer)
	all_items = frappe.db.sql(
		"""
		SELECT 
			name as item_code,
			custom_buffer_flag,
			custom_item_type,
			safety_stock as tog,
			min_order_qty as moq,
			custom_batch_size as batch_size
		FROM `tabItem`
		WHERE disabled = 0
		""",
		as_dict=True,
	)

	# Create maps for quick lookup
	item_buffer_map = {}  # item_code -> 'Buffer' or 'Non-Buffer'
	item_tog_map = {}  # item_code -> TOG value
	item_type_map = {}  # item_code -> item_type
	item_sku_type_map = {}  # item_code -> SKU type
	item_moq_map = {}  # item_code -> MOQ value
	item_batch_size_map = {}  # item_code -> Batch Size value

	for item in all_items:
		item_code = item.item_code
		buffer_flag = item.custom_buffer_flag or "Non-Buffer"
		item_type = item.custom_item_type
		item_buffer_map[item_code] = buffer_flag
		item_tog_map[item_code] = flt(item.tog or 0)
		item_type_map[item_code] = item_type
		item_sku_type_map[item_code] = calculate_sku_type(buffer_flag, item_type)
		item_moq_map[item_code] = flt(item.moq or 0)
		item_batch_size_map[item_code] = flt(item.batch_size or 0)

	# Get stock map for all items
	all_item_codes = set(item_buffer_map.keys())
	stock_map = get_stock_map_for_mrp(all_item_codes)

	# Get WIP map for all items
	wip_map = get_wip_map_for_mrp()

	# Get Open SO map for all items (for non-buffer items)
	open_so_map = get_open_so_map_for_mrp()

	# Get Qualified Demand map (Open SO with delivery_date <= today) - for buffer items
	qualified_demand_map = get_qualified_demand_map_for_mrp()

	# Get Open PO map (Purchase Order quantity - received quantity) - for BOTA/PTA buffer items
	open_po_map = get_open_po_map_for_mrp()

	# Get MRQ map (Material Request Quantity - sum of qty from Material Request Items with status 'Pending')
	mrq_map = get_mrq_map_for_mrp()

	# Initialize parent demand map (for non-buffer items)
	# This will accumulate parent demands from all BOMs
	parent_demand_map = {}  # item_code -> total parent demand from all BOMs

	# Detailed tracking for logging
	detailed_info = {}  # item_code -> detailed information dict

	# Step 1: Calculate initial order recommendations for all items
	# Buffer: TOG - Stock - WIP
	# Non-buffer: Open SO - Stock - WIP
	initial_order_recommendations = {}

	# Initialize detailed info for all items
	for item_code in all_item_codes:
		buffer_flag = item_buffer_map.get(item_code, "Non-Buffer")
		is_buffer = buffer_flag == "Buffer"
		stock = flt(stock_map.get(item_code, 0))
		wip = flt(wip_map.get(item_code, 0))
		open_so = flt(open_so_map.get(item_code, 0))
		tog = flt(item_tog_map.get(item_code, 0))
		qualified_demand = flt(qualified_demand_map.get(item_code, 0))
		open_po = flt(open_po_map.get(item_code, 0))
		mrq = flt(mrq_map.get(item_code, 0))
		item_type = item_type_map.get(item_code)
		sku_type = item_sku_type_map.get(item_code)

		detailed_info[item_code] = {
			"item_code": item_code,
			"buffer_flag": buffer_flag,
			"is_buffer": is_buffer,
			"item_type": item_type,
			"sku_type": sku_type,
			"tog": tog,
			"qualified_demand": qualified_demand,
			"open_so": open_so,
			"stock": stock,
			"wip": wip,
			"open_po": open_po,
			"mrq": mrq,
			"parent_demands": [],  # List of {parent_item, bom_name, demand_qty}
			"total_parent_demand": 0,
			"initial_order_rec": 0,
			"final_order_rec": 0,
			"calculation_breakdown": "",
		}

		order_rec = calculate_initial_order_recommendation(
			item_code,
			item_buffer_map,
			item_tog_map,
			item_sku_type_map,
			stock_map,
			wip_map,
			open_so_map,
			qualified_demand_map,
			open_po_map,
		)
		initial_order_recommendations[item_code] = order_rec
		detailed_info[item_code]["initial_order_rec"] = order_rec

	# Step 1.5: Apply MOQ/Batch Size to initial order recommendations for parent items
	# This ensures parent items use net order recommendations when traversing BOMs
	initial_net_order_recommendations = {}
	for item_code in all_item_codes:
		base_order_rec = initial_order_recommendations.get(item_code, 0)
		moq = flt(item_moq_map.get(item_code, 0))
		batch_size = flt(item_batch_size_map.get(item_code, 0))
		net_order_rec = calculate_net_order_recommendation(base_order_rec, moq, batch_size)
		initial_net_order_recommendations[item_code] = net_order_rec

	# Step 2: Traverse BOMs starting from items with net order recommendations > 0
	# We need to process all items that have initial net order recommendations
	# Get all items with net order recommendations > 0, sorted for consistent processing
	items_to_process = [
		(item_code, net_order_rec)
		for item_code, net_order_rec in initial_net_order_recommendations.items()
		if net_order_rec > 0
	]
	items_to_process.sort(key=lambda x: x[0])  # Sort by item_code

	# Process each item with net order recommendation > 0
	# Each traversal uses its own visited_items set to prevent circular references
	# But parent_demand_map accumulates demands from all traversals
	for item_code, net_order_rec in items_to_process:
		traverse_bom_for_mrp(
			item_code,
			net_order_rec,  # Use net order recommendation (after MOQ/Batch Size)
			item_buffer_map,
			item_tog_map,
			item_type_map,
			item_sku_type_map,
			stock_map,
			wip_map,
			open_so_map,
			qualified_demand_map,
			open_po_map,
			mrq_map,
			parent_demand_map,
			detailed_info,
			set(),  # visited_items for this traversal (prevents circular references)
			level=0,
		)

	# Step 3: Calculate final order recommendations for all items
	# Now parent_demand_map has accumulated all parent demands
	final_order_recommendations = {}

	for item_code in all_item_codes:
		# Update total_parent_demand in detailed_info
		if item_code in detailed_info:
			detailed_info[item_code]["total_parent_demand"] = flt(parent_demand_map.get(item_code, 0))

		# Calculate base order recommendation (with MRQ already subtracted)
		order_rec = calculate_final_order_recommendation(
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
		)

		final_order_recommendations[item_code] = order_rec

	# Step 4: Apply MOQ/Batch Size to get net order recommendations
	net_order_recommendations = {}  # item_code -> net order recommendation (after MOQ/Batch Size)

	for item_code in all_item_codes:
		base_order_rec = final_order_recommendations.get(item_code, 0)
		moq = flt(item_moq_map.get(item_code, 0))
		batch_size = flt(item_batch_size_map.get(item_code, 0))
		net_order_rec = calculate_net_order_recommendation(base_order_rec, moq, batch_size)
		net_order_recommendations[item_code] = net_order_rec

	# Step 5: Re-traverse BOMs using net_order_recommendations to update child requirements
	# This ensures children get the adjusted values (after MOQ/Batch Size) from their parents
	# Clear parent_demand_map and recalculate with net_order_recommendations
	parent_demand_map_net = {}  # New parent demand map using net order recommendations

	# Clear parent_demands from detailed_info to avoid duplicates from first traversal
	# We'll rebuild them in the second traversal
	for item_code in all_item_codes:
		if item_code in detailed_info:
			detailed_info[item_code]["parent_demands"] = []
			detailed_info[item_code]["total_parent_demand"] = 0

	# Get items with net_order_recommendation > 0
	# Only get items that are NOT children of other items (root items only)
	# We'll traverse from root items, and children will be handled recursively
	items_with_net_rec = [
		(item_code, net_rec) for item_code, net_rec in net_order_recommendations.items() if net_rec > 0
	]
	items_with_net_rec.sort(key=lambda x: x[0])  # Sort by item_code

	# Use a single shared visited_items set for the entire Step 5 traversal
	# This prevents the same item from being traversed multiple times
	global_visited_items = set()

	# Re-traverse BOMs using net_order_recommendations
	# Only traverse items that haven't been visited yet (to avoid duplicates)
	for item_code, net_rec in items_with_net_rec:
		if item_code not in global_visited_items:
			traverse_bom_for_mrp_with_net_rec(
				item_code,
				net_rec,
				item_buffer_map,
				item_tog_map,
				item_type_map,
				item_sku_type_map,
				item_moq_map,
				item_batch_size_map,
				stock_map,
				wip_map,
				open_so_map,
				qualified_demand_map,
				open_po_map,
				mrq_map,
				parent_demand_map_net,
				detailed_info,
				global_visited_items,  # Use shared visited_items set
				level=0,
			)

	# Step 6: Recalculate final order recommendations with updated parent demands
	# Then apply MOQ/Batch Size again to get final net_order_recommendations
	final_order_recommendations_updated = {}
	net_order_recommendations_final = {}

	for item_code in all_item_codes:
		# Recalculate with updated parent demands
		order_rec = calculate_final_order_recommendation(
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
			parent_demand_map_net,  # Use updated parent demands
		)
		final_order_recommendations_updated[item_code] = order_rec

		# Apply MOQ/Batch Size again
		moq = flt(item_moq_map.get(item_code, 0))
		batch_size = flt(item_batch_size_map.get(item_code, 0))
		net_order_rec = calculate_net_order_recommendation(order_rec, moq, batch_size)
		net_order_recommendations_final[item_code] = net_order_rec

		# Update detailed_info
		if item_code in detailed_info:
			detailed_info[item_code]["final_order_rec"] = order_rec
			detailed_info[item_code]["net_order_rec"] = net_order_rec

		# Ensure detailed_info exists for this item
		if item_code not in detailed_info:
			buffer_flag = item_buffer_map.get(item_code, "Non-Buffer")
			detailed_info[item_code] = {
				"item_code": item_code,
				"buffer_flag": buffer_flag,
				"is_buffer": buffer_flag == "Buffer",
				"item_type": item_type_map.get(item_code),
				"sku_type": item_sku_type_map.get(item_code),
				"tog": flt(item_tog_map.get(item_code, 0)),
				"qualified_demand": flt(qualified_demand_map.get(item_code, 0)),
				"open_so": flt(open_so_map.get(item_code, 0)),
				"stock": flt(stock_map.get(item_code, 0)),
				"wip": flt(wip_map.get(item_code, 0)),
				"open_po": flt(open_po_map.get(item_code, 0)),
				"mrq": flt(mrq_map.get(item_code, 0)),
				"moq": moq,
				"batch_size": batch_size,
				"parent_demands": [],
				"total_parent_demand": flt(parent_demand_map_net.get(item_code, 0)),
				"initial_order_rec": initial_order_recommendations.get(item_code, 0),
				"final_order_rec": order_rec,
				"net_order_rec": net_order_rec,
				"calculation_breakdown": "",
			}

		# Update detailed_info with final values
		if item_code in detailed_info:
			detailed_info[item_code]["final_order_rec"] = order_rec
			detailed_info[item_code]["net_order_rec"] = net_order_rec
			moq = flt(item_moq_map.get(item_code, 0))
			batch_size = flt(item_batch_size_map.get(item_code, 0))
			detailed_info[item_code]["moq"] = moq
			detailed_info[item_code]["batch_size"] = batch_size

		# Build calculation breakdown for ALL items (even if net_order_rec is 0)
		# Ensure item is in detailed_info (should always be true at this point)
		if item_code not in detailed_info:
			# This shouldn't happen, but create it if missing
			buffer_flag = item_buffer_map.get(item_code, "Non-Buffer")
			detailed_info[item_code] = {
				"item_code": item_code,
				"buffer_flag": buffer_flag,
				"is_buffer": buffer_flag == "Buffer",
				"item_type": item_type_map.get(item_code),
				"sku_type": item_sku_type_map.get(item_code),
				"tog": flt(item_tog_map.get(item_code, 0)),
				"qualified_demand": flt(qualified_demand_map.get(item_code, 0)),
				"open_so": flt(open_so_map.get(item_code, 0)),
				"stock": flt(stock_map.get(item_code, 0)),
				"wip": flt(wip_map.get(item_code, 0)),
				"open_po": flt(open_po_map.get(item_code, 0)),
				"mrq": flt(mrq_map.get(item_code, 0)),
				"moq": moq,
				"batch_size": batch_size,
				"parent_demands": [],
				"total_parent_demand": flt(parent_demand_map_net.get(item_code, 0)),
				"initial_order_rec": initial_order_recommendations.get(item_code, 0),
				"final_order_rec": order_rec,
				"net_order_rec": net_order_rec,
				"calculation_breakdown": "",
			}
			frappe.log_error(
				f"Item {item_code} was missing from detailed_info in Step 6 - created it",
				"MRP Generation Warning",
			)

		# Now build the breakdown for ALL items
		info = detailed_info[item_code]
		build_calculation_breakdown(info, parent_demand_map_net)  # Use updated parent demands

		# Verify breakdown was created (for debugging)
		if not info.get("calculation_breakdown") or not info["calculation_breakdown"].strip():
			frappe.log_error(
				f"Item {item_code} has empty calculation_breakdown after build_calculation_breakdown",
				"MRP Generation Warning",
			)

	# Generate detailed log - ensure all items with net_order_rec > 0 are included
	detailed_log = generate_detailed_log(detailed_info, net_order_recommendations_final)

	# Log to console (will be visible in server logs)
	frappe.log_error(detailed_log, "MRP Generation")

	# Also print to console for immediate visibility
	print(detailed_log)

	# Get job_id for logging and caching
	job_id = None
	try:
		job = frappe.get_job()
		if job and hasattr(job, "id"):
			job_id = job.id
	except:
		pass

	if not job_id:
		# Try to get from cache (stored when job was enqueued)
		job_id = frappe.cache().get_value(f"mrp_job_id_{frappe.session.user}")

	result = {
		"order_recommendations": final_order_recommendations_updated,
		"net_order_recommendations": net_order_recommendations_final,  # Final net order recommendations after MOQ/Batch Size
		"detailed_info": detailed_info,
		"message": "Order recommendations calculated. Check server logs and console for detailed breakdown. Net order recommendations are shown.",
		"status": "completed",
	}

	# Store result in cache for retrieval using job_id
	if job_id:
		cache_key = f"mrp_result_{job_id}"
		frappe.cache().set_value(cache_key, result, expires_in_sec=3600)  # Store for 1 hour

	# Log job completion
	items_with_rec = len([qty for qty in net_order_recommendations_final.values() if flt(qty) > 0])
	completion_msg = (
		f"[MRP Job {job_id or 'Unknown'}] Completed! Items with net order rec > 0: {items_with_rec}"
	)
	print(completion_msg)
	frappe.log_error(completion_msg, "MRP Generation Job")

	return result


@frappe.whitelist()
def get_mr_creation_progress(job_id):
	"""
	Get progress of Material Request creation job.
	Returns: current, total, percent, current_item, success_count, error_count
	"""
	if not job_id:
		return {"error": "Job ID is required"}

	progress_cache_key = f"mr_creation_progress_{job_id}"
	progress = frappe.cache().get_value(progress_cache_key)

	if progress:
		return progress
	else:
		return {
			"current": 0,
			"total": 0,
			"percent": 0,
			"current_item": None,
			"success_count": 0,
			"error_count": 0,
		}


@frappe.whitelist()
def get_mrp_job_status(job_id):
	"""
	Check the status of an MRP generation job.
	Returns: status (queued/running/completed/failed), result (if completed), error (if failed)
	"""
	if not job_id:
		return {"error": "Job ID is required"}

	try:
		# Check if result is available in cache (try both MRP and MR creation cache keys)
		cache_key_mrp = f"mrp_result_{job_id}"
		cache_key_mr = f"mr_creation_result_{job_id}"
		result = frappe.cache().get_value(cache_key_mrp) or frappe.cache().get_value(cache_key_mr)

		if result:
			return {
				"status": "completed",
				"result": result,
			}

		# Check job status using frappe's job system
		from rq import get_current_job
		from rq.job import Job

		try:
			job = Job.fetch(job_id, connection=frappe.utils.redis_conn())

			if job.is_finished:
				# Job finished, check if result is in cache
				result = frappe.cache().get_value(cache_key_mr)  # noqa: F821
				if result:
					return {
						"status": "completed",
						"result": result,
					}
				else:
					return {
						"status": "completed",
						"message": "Job completed but result not found in cache. It may have expired.",
					}
			elif job.is_failed:
				return {
					"status": "failed",
					"error": str(job.exc_info) if hasattr(job, "exc_info") else "Job failed",
				}
			elif job.is_started:
				return {
					"status": "running",
					"message": "Job is currently running...",
				}
			else:
				return {
					"status": "queued",
					"message": "Job is queued and waiting to start...",
				}
		except Exception as e:
			# Job might not exist or connection issue
			return {
				"status": "unknown",
				"error": f"Could not fetch job status: {str(e)}",
			}
	except Exception as e:
		return {
			"status": "error",
			"error": f"Error checking job status: {str(e)}",
		}


@frappe.whitelist()
def get_mrp_job_result(job_id):
	"""
	Get the result of a completed MRP generation job.
	"""
	if not job_id:
		return {"error": "Job ID is required"}

	cache_key = f"mrp_result_{job_id}"
	result = frappe.cache().get_value(cache_key)

	if result:
		return result
	else:
		return {
			"error": "Result not found. The job may not be completed yet, or the result may have expired.",
		}


@frappe.whitelist()
def get_mr_creation_progress(job_id):  # noqa: F811
	"""
	Get progress of Material Request creation job.
	Returns: current, total, percent, current_item, success_count, error_count
	"""
	if not job_id:
		return {"error": "Job ID is required"}

	progress_cache_key = f"mr_creation_progress_{job_id}"
	progress = frappe.cache().get_value(progress_cache_key)

	if progress:
		# Ensure all fields are present
		return {
			"current": progress.get("current", 0),
			"total": progress.get("total", 0),
			"percent": progress.get("percent", 0),
			"current_item": progress.get("current_item"),
			"success_count": progress.get("success_count", 0),
			"error_count": progress.get("error_count", 0),
		}
	else:
		# Progress not found - might be queued or just started
		return {
			"current": 0,
			"total": 0,
			"percent": 0,
			"current_item": None,
			"success_count": 0,
			"error_count": 0,
		}


@frappe.whitelist()
def list_active_mrp_jobs():
	"""
	List all active MRP-related jobs for the current user.
	This helps users see what jobs are running.
	"""
	import time

	active_jobs = []

	# Get MRP calculation job
	mrp_job_id = frappe.cache().get_value(f"mrp_job_id_{frappe.session.user}")
	if mrp_job_id:
		try:
			from rq.job import Job

			job = Job.fetch(mrp_job_id, connection=frappe.utils.redis_conn())
			active_jobs.append(
				{
					"job_id": mrp_job_id,
					"type": "MRP Calculation",
					"status": "finished"
					if job.is_finished
					else ("failed" if job.is_failed else ("started" if job.is_started else "queued")),
					"created_at": str(job.created_at) if hasattr(job, "created_at") else None,
				}
			)
		except:
			active_jobs.append(
				{
					"job_id": mrp_job_id,
					"type": "MRP Calculation",
					"status": "unknown",
				}
			)

	# Get MR creation job
	mr_job_id = frappe.cache().get_value(f"mr_creation_job_id_{frappe.session.user}")
	if mr_job_id:
		try:
			from rq.job import Job

			job = Job.fetch(mr_job_id, connection=frappe.utils.redis_conn())
			active_jobs.append(
				{
					"job_id": mr_job_id,
					"type": "Material Request Creation",
					"status": "finished"
					if job.is_finished
					else ("failed" if job.is_failed else ("started" if job.is_started else "queued")),
					"created_at": str(job.created_at) if hasattr(job, "created_at") else None,
				}
			)
		except:
			active_jobs.append(
				{
					"job_id": mr_job_id,
					"type": "Material Request Creation",
					"status": "unknown",
				}
			)

	return {
		"active_jobs": active_jobs,
		"count": len(active_jobs),
	}


@frappe.whitelist()
def create_material_request(item_code, qty):
	"""
	Create and submit a Material Request for the given item_code and quantity
	"""
	if not item_code:
		return {"error": "Item code is required"}

	if not qty or flt(qty) <= 0:
		return {"error": "Quantity must be greater than 0"}

	# Get item details
	if not frappe.db.exists("Item", item_code):
		return {"error": f"Item {item_code} not found"}

	item_doc = frappe.get_doc("Item", item_code)

	# Get item type from item
	item_type = item_doc.get("custom_item_type")

	# Set material_request_type based on item type
	# BB (Bright Bar) or RB (Round Bar): Manufacture
	# All other item types: Purchase
	if item_type in ["BB", "RB"]:
		material_request_type = "Manufacture"
	else:
		material_request_type = "Purchase"

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
	company = "RAMLAL DUGAR"

	# Verify company exists
	if not frappe.db.exists("Company", company):
		return {"error": f"Company '{company}' not found in the system."}

	try:
		# Set warehouse
		warehouse = "Finished Goods - RD"

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
				"material_request_type": material_request_type,
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
		frappe.log_error(
			f"Error creating Material Request: {str(e)}",
			"Create Material Request Error",
		)
		return {"error": f"Error creating Material Request: {str(e)}"}


@frappe.whitelist()
def create_material_requests_automatically(net_order_recommendations=None):
	"""
	Create Material Requests automatically for all items with order_recommendation > 0
	If an item has batch_size, create multiple Material Requests, each with batch_size quantity

	Args:
	        net_order_recommendations: Dict of item_code -> net_order_recommendation (optional)
	                Can be a dict or JSON string. If not provided, will enqueue as background job
	"""
	# Parse net_order_recommendations if it's a string (JSON)
	if isinstance(net_order_recommendations, str):
		import json

		try:
			net_order_recommendations = json.loads(net_order_recommendations)
		except (json.JSONDecodeError, ValueError):
			return {
				"error": f"Invalid JSON format for net_order_recommendations: {net_order_recommendations}",
			}

	if net_order_recommendations is None:
		# Enqueue as background job (without parameters - will get from cache)
		job = frappe.enqueue(
			"prakash_steel.prakash_steel.doctype.mrp_genaration.mrp_genaration._create_material_requests_worker",
			queue="long",
			timeout=1800,  # 30 minutes timeout
			job_name=f"MRP Material Request Creation - {frappe.session.user}",
			is_async=True,
			now=False,  # Ensure it's queued, not executed immediately
		)

		job_id = job.id if hasattr(job, "id") else str(job)
		frappe.cache().set_value(f"mr_creation_job_id_{frappe.session.user}", job_id, expires_in_sec=1800)

		# Log job creation
		print(
			f"[MR Creation] Job queued with ID: {job_id}, Name: MRP Material Request Creation - {frappe.session.user}"
		)
		frappe.log_error(f"MR Creation job queued: {job_id}", "MR Creation Job")

		return {
			"job_id": job_id,
			"status": "queued",
			"message": f"Material Request creation job has been queued (Job ID: {job_id}). Check 'RQ Job' list to monitor progress.",
		}
	else:
		# Store net_order_recommendations in cache for the worker to retrieve
		# This is needed because enqueue might not serialize complex objects correctly
		cache_key = f"mr_net_order_recs_{frappe.session.user}"
		frappe.cache().set_value(cache_key, net_order_recommendations, expires_in_sec=1800)

		# Enqueue as background job
		job = frappe.enqueue(
			"prakash_steel.prakash_steel.doctype.mrp_genaration.mrp_genaration._create_material_requests_worker",
			net_order_recommendations=net_order_recommendations,  # Pass as parameter
			queue="long",
			timeout=1800,  # 30 minutes timeout
			job_name=f"MRP Material Request Creation - {frappe.session.user}",
			is_async=True,
			now=False,  # Ensure it's queued, not executed immediately
		)

		job_id = job.id if hasattr(job, "id") else str(job)
		frappe.cache().set_value(f"mr_creation_job_id_{frappe.session.user}", job_id, expires_in_sec=1800)

		# Log job creation
		print(
			f"[MR Creation] Job queued with ID: {job_id}, Name: MRP Material Request Creation - {frappe.session.user}"
		)
		frappe.log_error(f"MR Creation job queued: {job_id}", "MR Creation Job")

		return {
			"job_id": job_id,
			"status": "queued",
			"message": f"Material Request creation job has been queued (Job ID: {job_id}). Check 'RQ Job' list to monitor progress.",
		}


def _create_material_requests_worker(net_order_recommendations=None):
	"""
	Worker function that creates Material Requests.
	This runs as a background job to prevent UI blocking.
	"""
	# Log job start
	job_id = None
	try:
		job = frappe.get_job()
		if job and hasattr(job, "id"):
			job_id = job.id
	except:  # noqa: E722
		pass

	if not job_id:
		job_id = frappe.cache().get_value(f"mr_creation_job_id_{frappe.session.user}")

	start_msg = f"[MR Creation Job {job_id or 'Unknown'}] Starting Material Request creation..."
	print(start_msg)
	frappe.log_error(start_msg, "MR Creation Job")

	# If not provided as parameter, try to get from cache
	if net_order_recommendations is None:
		cache_key = f"mr_net_order_recs_{frappe.session.user}"
		net_order_recommendations = frappe.cache().get_value(cache_key)

	# Parse if it's a string (JSON)
	if isinstance(net_order_recommendations, str):
		import json

		try:
			net_order_recommendations = json.loads(net_order_recommendations)
		except (json.JSONDecodeError, ValueError):
			return {
				"success_count": 0,
				"error_count": 1,
				"material_requests": [],
				"errors": ["Invalid JSON format for net_order_recommendations"],
				"message": "Failed to parse net_order_recommendations",
			}

	# Validate that it's a dict
	if not isinstance(net_order_recommendations, dict):
		return {
			"success_count": 0,
			"error_count": 1,
			"material_requests": [],
			"errors": [
				f"Expected dict, got {type(net_order_recommendations).__name__ if net_order_recommendations else 'None'}"
			],
			"message": "Invalid format for net_order_recommendations",
		}

	if not net_order_recommendations:
		return {
			"success_count": 0,
			"error_count": 0,
			"material_requests": [],
			"message": "No order recommendations provided",
		}

	# Get detailed_info from cache if available (from MRP calculation)
	detailed_info = {}
	try:
		# Try to get from the most recent MRP result
		job_id = frappe.cache().get_value(f"mrp_job_id_{frappe.session.user}")
		if job_id:
			cache_key = f"mrp_result_{job_id}"
			mrp_result = frappe.cache().get_value(cache_key)
			if mrp_result:
				detailed_info = mrp_result.get("detailed_info", {})
	except:
		pass

	# Filter items with net_order_recommendation > 0
	items_to_process = [
		(item_code, qty) for item_code, qty in net_order_recommendations.items() if flt(qty) > 0
	]

	if not items_to_process:
		return {
			"success_count": 0,
			"error_count": 0,
			"material_requests": [],
			"message": "No items with Net Order Recommendation > 0 found",
		}

	total_items = len(items_to_process)
	success_count = 0
	error_count = 0
	material_requests = []
	errors = []

	# Store progress in cache for frontend polling
	progress_cache_key = f"mr_creation_progress_{job_id}"

	def update_progress(current, total, current_item=None):
		"""Update progress in cache"""
		progress = {
			"current": current,
			"total": total,
			"percent": int((current / total) * 100) if total > 0 else 0,
			"current_item": current_item,
			"success_count": success_count,
			"error_count": error_count,
		}
		frappe.cache().set_value(progress_cache_key, progress, expires_in_sec=1800)
		# Also print for debugging
		print(
			f"[MR Creation Progress] {current}/{total} ({progress['percent']}%) - Item: {current_item}, Success: {success_count}, Failed: {error_count}"
		)

	# Initialize progress at start
	update_progress(0, total_items, None)

	# Create Material Request(s) for each item
	for idx, (item_code, net_qty) in enumerate(items_to_process, 1):
		# Update progress before processing item
		update_progress(idx, total_items, item_code)
		if not item_code or net_qty <= 0:
			error_count += 1
			errors.append(f"{item_code}: Invalid quantity")
			continue

		try:
			# Get batch_size for this item
			batch_size = 0
			if item_code in detailed_info:
				batch_size = flt(detailed_info[item_code].get("batch_size", 0))
			else:
				# Fallback: get from item doctype
				item_doc = frappe.get_doc("Item", item_code)
				batch_size = flt(item_doc.get("custom_batch_size", 0))

			if batch_size > 0:
				# Item has batch_size - create multiple Material Requests
				# Since net_order_recommendation is already adjusted to be a multiple of batch_size,
				# we just need to divide to get the number of Material Requests
				# Example: net_qty = 1600, batch_size = 400 -> 4 Material Requests of 400 each
				num_requests = int(flt(net_qty) / flt(batch_size))

				# Create Material Requests, each with batch_size quantity
				for i in range(num_requests):
					result = create_material_request(item_code, batch_size)
					if result.get("error"):
						error_count += 1
						errors.append(f"{item_code} (MR #{i + 1} of {num_requests}): {result.get('error')}")
					else:
						success_count += 1
						material_requests.append(result.get("material_request"))
					# Update progress after each MR creation
					update_progress(idx, total_items, item_code)

				# Handle remainder (shouldn't happen if net_order_recommendation is properly calculated, but just in case)
				remainder = flt(net_qty) % flt(batch_size)
				if remainder > 0:
					# Create one more Material Request with the remainder
					result = create_material_request(item_code, remainder)
					if result.get("error"):
						error_count += 1
						errors.append(f"{item_code} (Remainder {remainder}): {result.get('error')}")
					else:
						success_count += 1
						material_requests.append(result.get("material_request"))
			else:
				# No batch_size - create single Material Request with full quantity
				result = create_material_request(item_code, net_qty)
				if result.get("error"):
					error_count += 1
					errors.append(f"{item_code}: {result.get('error')}")
				else:
					success_count += 1
					material_requests.append(result.get("material_request"))
					# Update progress after successful creation
					update_progress(idx, total_items, item_code)
		except Exception as e:
			error_count += 1
			errors.append(f"{item_code}: {str(e)}")
			frappe.log_error(
				f"Error creating Material Request for {item_code}: {str(e)}",
				"Create Material Requests Automatically Error",
			)
			# Update progress even on error
			update_progress(idx, total_items, item_code)

	result = {
		"success_count": success_count,
		"error_count": error_count,
		"material_requests": material_requests,
		"errors": errors[:10] if len(errors) > 10 else errors,  # Limit errors to first 10
		"message": f"Created {success_count} Material Request(s), {error_count} failed",
		"status": "completed",
	}

	# Store result in cache for retrieval using job_id
	job_id = None
	try:
		job = frappe.get_job()
		if job and hasattr(job, "id"):
			job_id = job.id
	except:
		pass

	if not job_id:
		# Try to get from cache (stored when job was enqueued)
		job_id = frappe.cache().get_value(f"mr_creation_job_id_{frappe.session.user}")

	if job_id:
		cache_key = f"mr_creation_result_{job_id}"
		frappe.cache().set_value(cache_key, result, expires_in_sec=1800)  # Store for 30 minutes

		# Clear progress cache
		progress_cache_key = f"mr_creation_progress_{job_id}"
		frappe.cache().delete_value(progress_cache_key)

	# Log job completion
	completion_msg = f"[MR Creation Job {job_id or 'Unknown'}] Completed! Created {success_count} MR(s), {error_count} failed"
	print(completion_msg)
	frappe.log_error(completion_msg, "MR Creation Job")

	return result


def calculate_net_order_recommendation(base_order_rec, moq, batch_size):
	"""
	Calculate net order recommendation by applying MOQ/Batch Size logic.

	Logic:
	- If base_order_rec <= 0: return 0 (no order needed, ignore MOQ/Batch Size)
	- If MOQ > 0:
	  - If MOQ < base_order_rec: use base_order_rec
	  - If MOQ >= base_order_rec: use MOQ
	- Else if batch_size > 0:
	  - ceil(base_order_rec / batch_size) * batch_size
	- Else:
	  - Use base_order_rec as is
	"""
	base_order_rec = flt(base_order_rec)
	moq = flt(moq)
	batch_size = flt(batch_size)

	# If base order recommendation is 0 or negative, return 0
	# Don't apply MOQ/Batch Size for negative or zero demand
	if base_order_rec <= 0:
		return 0

	if moq > 0:
		# Use MOQ:
		# If MOQ < base_order_rec: use base_order_rec
		# If MOQ >= base_order_rec: use MOQ
		if moq < base_order_rec:
			net_order_rec = base_order_rec
		else:
			net_order_rec = moq
	elif batch_size > 0:
		# Use Batch Size: ceil(base_order_rec / batch_size) * batch_size
		net_order_rec = math.ceil(base_order_rec / batch_size) * batch_size
	else:
		# No MOQ or Batch Size, use base_order_rec as is
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
	"""
	Calculate initial order recommendation for a single item (before BOM traversal).
	- Buffer: TOG + Qualified Demand - Stock - WIP/Open PO
	  - For BOTA/PTA: TOG + Qualified Demand - Stock - WIP - Open PO
	  - For others: TOG + Qualified Demand - Stock - WIP
	- Non-buffer: Open SO - Stock - WIP
	"""
	buffer_flag = item_buffer_map.get(item_code, "Non-Buffer")
	is_buffer = buffer_flag == "Buffer"

	stock = flt(stock_map.get(item_code, 0))
	wip = flt(wip_map.get(item_code, 0))

	if is_buffer:
		# Buffer item: Order recommendation = TOG + Qualified Demand - Stock - WIP/Open PO
		tog = flt(item_tog_map.get(item_code, 0))
		qualified_demand = flt(qualified_demand_map.get(item_code, 0))
		sku_type = item_sku_type_map.get(item_code)
		open_po = flt(open_po_map.get(item_code, 0))

		if sku_type in ["BOTA", "PTA"]:
			# For BOTA/PTA: TOG + Qualified Demand - Stock - WIP - Open PO
			order_rec = max(0, tog + qualified_demand - stock - wip - open_po)
		else:
			# For other buffer items: TOG + Qualified Demand - Stock - WIP
			order_rec = max(0, tog + qualified_demand - stock - wip)
	else:
		# Non-buffer item: Order recommendation = max(0, Open SO - Stock - WIP)
		# For PTO and BOTO (purchase items): also subtract Open PO
		open_so = flt(open_so_map.get(item_code, 0))
		sku_type = item_sku_type_map.get(item_code)
		open_po = flt(open_po_map.get(item_code, 0))

		if sku_type in ["PTO", "BOTO"]:
			# For PTO/BOTO: Open SO - Stock - WIP - Open PO
			order_rec = max(0, open_so - stock - wip - open_po)
		else:
			# For other non-buffer items: Open SO - Stock - WIP
			order_rec = max(0, open_so - stock - wip)

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
	"""
	Calculate final order recommendation for a single item (after BOM traversal).
	- Buffer: TOG + Qualified Demand - Stock - WIP/Open PO - MRQ (parent demand ignored)
	  - For BOTA/PTA: TOG + Qualified Demand - Stock - WIP - Open PO - MRQ
	  - For others: TOG + Qualified Demand - Stock - WIP - MRQ
	- Non-buffer: max(0, (Open SO + Parent Demand) - Stock - WIP - MRQ)
	  - For PTO/BOTO: max(0, (Open SO + Parent Demand) - Stock - WIP - Open PO - MRQ)
	"""
	buffer_flag = item_buffer_map.get(item_code, "Non-Buffer")
	is_buffer = buffer_flag == "Buffer"

	stock = flt(stock_map.get(item_code, 0))
	wip = flt(wip_map.get(item_code, 0))
	mrq = flt(mrq_map.get(item_code, 0))

	if is_buffer:
		# Buffer item: Order recommendation = TOG + Qualified Demand - Stock - WIP/Open PO - MRQ (parent demand ignored)
		tog = flt(item_tog_map.get(item_code, 0))
		qualified_demand = flt(qualified_demand_map.get(item_code, 0))
		sku_type = item_sku_type_map.get(item_code)
		open_po = flt(open_po_map.get(item_code, 0))

		if sku_type in ["BOTA", "PTA"]:
			# For BOTA/PTA: TOG + Qualified Demand - Stock - WIP - Open PO - MRQ
			base_order_rec = tog + qualified_demand - stock - wip - open_po
		else:
			# For other buffer items: TOG + Qualified Demand - Stock - WIP - MRQ
			base_order_rec = tog + qualified_demand - stock - wip

		# Subtract MRQ from base order recommendation
		order_rec = max(0, base_order_rec - mrq)
	else:
		# Non-buffer item: Order recommendation = max(0, Requirement - Stock - WIP - MRQ)
		# Requirement = Open SO + sum of all parent BOM demands
		# For PTO and BOTO (purchase items): also subtract Open PO
		open_so = flt(open_so_map.get(item_code, 0))
		parent_demand = flt(parent_demand_map.get(item_code, 0))
		requirement = open_so + parent_demand
		sku_type = item_sku_type_map.get(item_code)
		open_po = flt(open_po_map.get(item_code, 0))

		if sku_type in ["PTO", "BOTO"]:
			# For PTO/BOTO: Requirement - Stock - WIP - Open PO - MRQ
			base_order_rec = requirement - stock - wip - open_po
		else:
			# For other non-buffer items: Requirement - Stock - WIP - MRQ
			base_order_rec = requirement - stock - wip

		# Subtract MRQ from base order recommendation
		order_rec = max(0, base_order_rec - mrq)

	return order_rec


def traverse_bom_for_mrp(
	parent_item_code,
	parent_order_qty,
	item_buffer_map,
	item_tog_map,
	item_type_map,
	item_sku_type_map,
	stock_map,
	wip_map,
	open_so_map,
	qualified_demand_map,
	open_po_map,
	mrq_map,
	parent_demand_map,
	detailed_info,
	visited_items,
	level=0,
):
	"""
	Recursively traverse BOM to calculate parent demands for child items.
	For buffer child items: Don't add parent demand (they use TOG-based calculation)
	For non-buffer child items: Add parent demand to requirement

	Args:
	        parent_item_code: Item code of parent item
	        parent_order_qty: Order quantity needed for parent item
	        detailed_info: Dict to store detailed information for each item
	        visited_items: Set of visited items in current traversal (to prevent circular references)
	"""
	if parent_item_code in visited_items:
		return

	visited_items.add(parent_item_code)

	# Get BOM for parent item
	bom = get_default_bom(parent_item_code)
	if not bom:
		return

	try:
		bom_doc = frappe.get_doc("BOM", bom)
		bom_name = bom_doc.name
		bom_quantity = flt(bom_doc.quantity)  # Quantity of parent item produced by this BOM
		if bom_quantity <= 0:
			bom_quantity = 1.0  # Default to 1 if BOM quantity is 0 or negative

		# Process each child item in BOM
		for bom_item in bom_doc.items:
			child_item_code = bom_item.item_code
			bom_item_qty = flt(bom_item.qty)  # Quantity of child item needed in BOM

			# Calculate required qty for child: parent_order_qty * (bom_item_qty / bom_quantity)
			# This normalizes the BOM item quantity to "per unit of parent item produced"
			# Example: If BOM produces 0.97 units of parent and needs 0.3 units of child,
			# then for 1 unit of parent, we need: 0.3 / 0.97 units of child
			normalized_bom_qty = bom_item_qty / bom_quantity
			child_required_qty = math.ceil(parent_order_qty * normalized_bom_qty)

			# Track parent demand in detailed_info
			if child_item_code not in detailed_info:
				# Initialize if not already done
				child_buffer_flag = item_buffer_map.get(child_item_code, "Non-Buffer")
				detailed_info[child_item_code] = {
					"item_code": child_item_code,
					"buffer_flag": child_buffer_flag,
					"is_buffer": child_buffer_flag == "Buffer",
					"item_type": item_type_map.get(child_item_code),
					"sku_type": item_sku_type_map.get(child_item_code),
					"tog": flt(item_tog_map.get(child_item_code, 0)),
					"qualified_demand": flt(qualified_demand_map.get(child_item_code, 0)),
					"open_so": flt(open_so_map.get(child_item_code, 0)),
					"stock": flt(stock_map.get(child_item_code, 0)),
					"wip": flt(wip_map.get(child_item_code, 0)),
					"open_po": flt(open_po_map.get(child_item_code, 0)),
					"mrq": flt(mrq_map.get(child_item_code, 0)),
					"parent_demands": [],
					"total_parent_demand": 0,
					"initial_order_rec": 0,
					"final_order_rec": 0,
					"calculation_breakdown": "",
				}

			# Check if child is buffer or non-buffer
			child_buffer_flag = item_buffer_map.get(child_item_code, "Non-Buffer")
			is_child_buffer = child_buffer_flag == "Buffer"

			if is_child_buffer:
				# Buffer child: Don't add parent demand (they use TOG + Qualified Demand calculation)
				# Record that parent demand was ignored (for logging)
				detailed_info[child_item_code]["parent_demands"].append(
					{
						"parent_item": parent_item_code,
						"bom_name": bom_name,
						"demand_qty": child_required_qty,
						"applied": False,  # Not applied because it's buffer
						"reason": "Buffer item - parent demand ignored, uses TOG + Qualified Demand calculation",
					}
				)

				# But we still need to traverse its BOM if it has order recommendation > 0
				# Calculate its order recommendation (TOG + Qualified Demand, ignoring parent demand)
				child_tog = flt(item_tog_map.get(child_item_code, 0))
				child_qualified_demand = flt(qualified_demand_map.get(child_item_code, 0))
				child_stock = flt(stock_map.get(child_item_code, 0))
				child_wip = flt(wip_map.get(child_item_code, 0))
				child_sku_type = item_sku_type_map.get(child_item_code)
				child_open_po = flt(open_po_map.get(child_item_code, 0))
				child_mrq = flt(mrq_map.get(child_item_code, 0))

				if child_sku_type in ["BOTA", "PTA"]:
					base_child_order_rec = (
						child_tog + child_qualified_demand - child_stock - child_wip - child_open_po
					)
				else:
					base_child_order_rec = child_tog + child_qualified_demand - child_stock - child_wip

				# Subtract MRQ from base order recommendation
				child_order_rec = max(0, base_child_order_rec - child_mrq)

				# If buffer child has order recommendation > 0, traverse its BOM
				# Use a new visited_items set to allow traversal (buffer items can be processed independently)
				if child_order_rec > 0 and child_item_code not in visited_items:
					traverse_bom_for_mrp(
						child_item_code,
						child_order_rec,
						item_buffer_map,
						item_tog_map,
						item_type_map,
						item_sku_type_map,
						stock_map,
						wip_map,
						open_so_map,
						qualified_demand_map,
						open_po_map,
						mrq_map,
						parent_demand_map,
						detailed_info,
						visited_items.copy(),  # New set for this branch
						level + 1,
					)
			else:
				# Non-buffer child: Add parent demand to requirement
				# Record parent demand
				detailed_info[child_item_code]["parent_demands"].append(
					{
						"parent_item": parent_item_code,
						"bom_name": bom_name,
						"demand_qty": child_required_qty,
						"applied": True,  # Applied to requirement
						"reason": f"From parent {parent_item_code} (Order Qty: {parent_order_qty}) × (BOM Item Qty: {bom_item_qty} / BOM Qty: {bom_quantity}) = {normalized_bom_qty:.4f}",
					}
				)

				# Accumulate parent demand (same item can appear in multiple BOMs)
				if child_item_code in parent_demand_map:
					parent_demand_map[child_item_code] += child_required_qty
				else:
					parent_demand_map[child_item_code] = child_required_qty

				# Update total parent demand in detailed_info
				detailed_info[child_item_code]["total_parent_demand"] = flt(
					parent_demand_map.get(child_item_code, 0)
				)

				# Calculate order recommendation for child item (with parent demand)
				child_open_so = flt(open_so_map.get(child_item_code, 0))
				child_parent_demand = flt(parent_demand_map.get(child_item_code, 0))
				child_requirement = child_open_so + child_parent_demand
				child_stock = flt(stock_map.get(child_item_code, 0))
				child_wip = flt(wip_map.get(child_item_code, 0))
				child_sku_type = item_sku_type_map.get(child_item_code)
				child_open_po = flt(open_po_map.get(child_item_code, 0))
				child_mrq = flt(mrq_map.get(child_item_code, 0))

				if child_sku_type in ["PTO", "BOTO"]:
					# For PTO/BOTO: Requirement - Stock - WIP - Open PO - MRQ
					base_child_order_rec = child_requirement - child_stock - child_wip - child_open_po
				else:
					# For other non-buffer items: Requirement - Stock - WIP - MRQ
					base_child_order_rec = child_requirement - child_stock - child_wip

				# Subtract MRQ from base order recommendation
				child_order_rec = max(0, base_child_order_rec - child_mrq)

				# If non-buffer child has order recommendation > 0, traverse its BOM recursively
				# Use a new visited_items set to allow traversal from different paths
				if child_order_rec > 0 and child_item_code not in visited_items:
					traverse_bom_for_mrp(
						child_item_code,
						child_order_rec,
						item_buffer_map,
						item_tog_map,
						item_type_map,
						item_sku_type_map,
						stock_map,
						wip_map,
						open_so_map,
						qualified_demand_map,
						open_po_map,
						mrq_map,
						parent_demand_map,
						detailed_info,
						visited_items.copy(),  # New set for this branch
						level + 1,
					)

	except Exception as e:
		frappe.log_error(
			f"Error traversing BOM for item {parent_item_code}: {str(e)}",
			"MRP Generation Error",
		)


def traverse_bom_for_mrp_with_net_rec(
	parent_item_code,
	parent_net_order_qty,
	item_buffer_map,
	item_tog_map,
	item_type_map,
	item_sku_type_map,
	item_moq_map,
	item_batch_size_map,
	stock_map,
	wip_map,
	open_so_map,
	qualified_demand_map,
	open_po_map,
	mrq_map,
	parent_demand_map,
	detailed_info,
	visited_items,
	level=0,
):
	"""
	Recursively traverse BOM using net_order_recommendations (after MOQ/Batch Size).
	This ensures children get the adjusted values from their parents.
	Similar to traverse_bom_for_mrp but uses net_order_recommendation values.
	"""
	if parent_item_code in visited_items:
		return

	visited_items.add(parent_item_code)

	# Get BOM for parent item
	bom = get_default_bom(parent_item_code)
	if not bom:
		return

	try:
		bom_doc = frappe.get_doc("BOM", bom)
		bom_name = bom_doc.name
		bom_quantity = flt(bom_doc.quantity)  # Quantity of parent item produced by this BOM
		if bom_quantity <= 0:
			bom_quantity = 1.0  # Default to 1 if BOM quantity is 0 or negative

		# Process each child item in BOM
		for bom_item in bom_doc.items:
			child_item_code = bom_item.item_code
			bom_item_qty = flt(bom_item.qty)  # Quantity of child item needed in BOM

			# Calculate required qty for child: parent_net_order_qty * (bom_item_qty / bom_quantity)
			# This normalizes the BOM item quantity to "per unit of parent item produced"
			# Example: If BOM produces 0.97 units of parent and needs 0.3 units of child,
			# then for 1 unit of parent, we need: 0.3 / 0.97 units of child
			# This uses the net_order_recommendation (after MOQ/Batch Size) of parent
			normalized_bom_qty = bom_item_qty / bom_quantity
			child_required_qty = parent_net_order_qty * normalized_bom_qty

			# Check if child is buffer or non-buffer
			child_buffer_flag = item_buffer_map.get(child_item_code, "Non-Buffer")
			is_child_buffer = child_buffer_flag == "Buffer"

			if is_child_buffer:
				# Buffer child: Don't add parent demand (they use TOG + Qualified Demand calculation)
				# But record it for logging
				if child_item_code in detailed_info:
					detailed_info[child_item_code]["parent_demands"].append(
						{
							"parent_item": parent_item_code,
							"bom_name": bom_name,
							"demand_qty": child_required_qty,
							"applied": False,
							"reason": f"Buffer item - parent demand ignored (from net_order_rec: {parent_net_order_qty})",
						}
					)
			else:
				# Non-buffer child: Add parent demand to requirement
				# Record parent demand
				if child_item_code in detailed_info:
					detailed_info[child_item_code]["parent_demands"].append(
						{
							"parent_item": parent_item_code,
							"bom_name": bom_name,
							"demand_qty": child_required_qty,
							"applied": True,
							"reason": f"From parent {parent_item_code} (Net Order Qty: {parent_net_order_qty}) × (BOM Item Qty: {bom_item_qty} / BOM Qty: {bom_quantity}) = {normalized_bom_qty:.4f}",
						}
					)

				# Accumulate parent demand (same item can appear in multiple BOMs)
				if child_item_code in parent_demand_map:
					parent_demand_map[child_item_code] += child_required_qty
				else:
					parent_demand_map[child_item_code] = child_required_qty

				# Update total parent demand in detailed_info
				if child_item_code in detailed_info:
					detailed_info[child_item_code]["total_parent_demand"] = flt(
						parent_demand_map.get(child_item_code, 0)
					)

				# Calculate order recommendation for child item (with parent demand)
				child_open_so = flt(open_so_map.get(child_item_code, 0))
				child_parent_demand = flt(parent_demand_map.get(child_item_code, 0))
				child_requirement = child_open_so + child_parent_demand
				child_stock = flt(stock_map.get(child_item_code, 0))
				child_wip = flt(wip_map.get(child_item_code, 0))
				child_sku_type = item_sku_type_map.get(child_item_code)
				child_open_po = flt(open_po_map.get(child_item_code, 0))
				child_mrq = flt(mrq_map.get(child_item_code, 0))

				if child_sku_type in ["PTO", "BOTO"]:
					base_child_order_rec = child_requirement - child_stock - child_wip - child_open_po
				else:
					base_child_order_rec = child_requirement - child_stock - child_wip

				# Subtract MRQ from base order recommendation
				child_base_order_rec = max(0, base_child_order_rec - child_mrq)

				# Apply MOQ/Batch Size to get net_order_recommendation
				child_moq = flt(item_moq_map.get(child_item_code, 0))
				child_batch_size = flt(item_batch_size_map.get(child_item_code, 0))
				child_net_order_rec = calculate_net_order_recommendation(
					child_base_order_rec, child_moq, child_batch_size
				)

				# If child has net_order_recommendation > 0, traverse its BOM recursively
				if child_net_order_rec > 0 and child_item_code not in visited_items:
					traverse_bom_for_mrp_with_net_rec(
						child_item_code,
						child_net_order_rec,
						item_buffer_map,
						item_tog_map,
						item_type_map,
						item_sku_type_map,
						item_moq_map,
						item_batch_size_map,
						stock_map,
						wip_map,
						open_so_map,
						qualified_demand_map,
						open_po_map,
						mrq_map,
						parent_demand_map,
						detailed_info,
						visited_items.copy(),
						level + 1,
					)

	except Exception as e:
		frappe.log_error(
			f"Error traversing BOM with net_rec for item {parent_item_code}: {str(e)}",
			"MRP Generation Error",
		)


def get_stock_map_for_mrp(item_codes):
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


def get_wip_map_for_mrp():
	"""Get WIP (Work In Progress) map - sum of (qty - produced_qty) from Work Order (where status is not Completed or Cancelled)
	for ALL items (all-time data)

	Note: We use only Work Order WIP to avoid double-counting, as work_order_qty in Sales Order Items
	typically reflects the same Work Order quantity. We calculate remaining quantity as qty - produced_qty.

	This function now checks Production Plan Settings to determine which method to use:
	- If "from_work_order" is checked: uses Work Order based calculation (existing logic)
	- If "from_production_plan" is checked: uses Production Plan based calculation (new logic)
	"""
	# Get Production Plan Settings
	try:
		settings = frappe.get_single("Production planning settings")
	except Exception:
		# If settings don't exist, default to work order method
		settings = frappe._dict({"from_work_order": 1, "from_production_plan": 0})

	wip_map = {}

	# Check which method is selected
	if settings.get("from_work_order"):
		# Existing logic: Get WIP from Work Order (qty - produced_qty) - only for Work Orders that are not Completed or Cancelled
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

		# Build WIP map from Work Orders only
		for row in wip_rows_wo:
			item_code = row.item_code
			wip_map[item_code] = flt(row.wip_qty)

	elif settings.get("from_production_plan"):
		# New logic: Get WIP from Production Plan
		# Get all Production Plans
		production_plans = frappe.get_all("Production Plan", filters={"docstatus": 1}, fields=["name"])

		for pp in production_plans:
			pp_name = pp.name

			# Get Production Plan document to access po_items child table
			try:
				pp_doc = frappe.get_doc("Production Plan", pp_name)

				# Check if po_items child table exists
				if hasattr(pp_doc, "po_items") and pp_doc.po_items:
					# Iterate through each item in po_items
					for po_item in pp_doc.po_items:
						item_code = po_item.item_code
						planned_qty = flt(po_item.planned_qty) if po_item.planned_qty else 0

						if not item_code:
							continue

						# Get all submitted Finished Weight documents linked to this Production Plan
						# Get individual documents with their finish_weight values for breakdown
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

						# Get all submitted Bright Bar Production documents linked to this Production Plan
						# Get individual documents with their fg_weight values for breakdown
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

						# Total finished = finish_weight + fg_weight
						total_finished = total_finished_from_fw + total_finished_from_bbp

						# Calculate WIP: planned_qty - sum of all finish_weight and fg_weight
						wip_qty = max(0, planned_qty - total_finished)  # Ensure non-negative

						# Build WIP calculation breakdown
						breakdown_lines = []
						breakdown_lines.append("=" * 80)
						breakdown_lines.append(f"WIP Calculation Breakdown (MRP Generation)")
						breakdown_lines.append("=" * 80)
						breakdown_lines.append(f"Production Plan: {pp_name}")
						breakdown_lines.append(f"Item Code: {item_code}")
						breakdown_lines.append(f"Planned Quantity: {planned_qty}")
						breakdown_lines.append("")
						breakdown_lines.append("Finish Weight Documents:")
						if finished_weight_docs:
							for fw_doc in finished_weight_docs:
								breakdown_lines.append(
									f"  - {fw_doc.name}: finish_weight = {flt(fw_doc.finish_weight)}"
								)
							breakdown_lines.append(f"  Total from Finish Weight: {total_finished_from_fw}")
						else:
							breakdown_lines.append("  (No Finish Weight documents found)")
							breakdown_lines.append("  Total from Finish Weight: 0")
						breakdown_lines.append("")
						breakdown_lines.append("Bright Bar Production Documents:")
						if bright_bar_production_docs:
							for bbp_doc in bright_bar_production_docs:
								breakdown_lines.append(
									f"  - {bbp_doc.name}: fg_weight = {flt(bbp_doc.fg_weight)}"
								)
							breakdown_lines.append(
								f"  Total from Bright Bar Production: {total_finished_from_bbp}"
							)
						else:
							breakdown_lines.append("  (No Bright Bar Production documents found)")
							breakdown_lines.append("  Total from Bright Bar Production: 0")
						breakdown_lines.append("")
						breakdown_lines.append(
							f"Total Finished: {total_finished_from_fw} + {total_finished_from_bbp} = {total_finished}"
						)
						breakdown_lines.append(
							f"WIP Calculation: Planned Qty - Total Finished = {planned_qty} - {total_finished} = {wip_qty}"
						)
						breakdown_lines.append("=" * 80)

						# Log the breakdown
						breakdown_str = "\n".join(breakdown_lines)
						print(breakdown_str)
						frappe.log_error(
							breakdown_str,
							"WIP Calculation Breakdown (MRP Generation)",
						)

						# Add to wip_map (sum if item_code already exists from another production plan)
						if item_code in wip_map:
							wip_map[item_code] += wip_qty
						else:
							wip_map[item_code] = wip_qty

			except Exception as e:
				frappe.log_error(
					f"Error processing Production Plan {pp_name} in get_wip_map_for_mrp: {str(e)}",
					"MRP Generation WIP Calculation Error",
				)
				continue

	return wip_map


def get_open_so_map_for_mrp():
	"""Get Open SO map - sum of max(0, qty - delivered_qty) from Sales Order Items
	IMPORTANT: This calculates OPEN SO (qty - delivered_qty), NOT total SO (qty).
	Open SO = Sales Orders with delivery_date <= today (only those with delivery date today or in the past).
	Total SO = All Sales Orders regardless of delivery date (not used here).
	For each Sales Order Item, if delivered_qty >= qty (over-delivered), treat as 0.
	This ensures over-delivery on one SO doesn't reduce open quantity of another SO.
	"""
	from frappe.utils import today

	today_date = today()

	so_rows = frappe.db.sql(
		"""
		SELECT
			soi.item_code,
			SUM(GREATEST(0, soi.qty - IFNULL(soi.delivered_qty, 0))) as so_qty
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


def get_qualified_demand_map_for_mrp():
	"""Get qualified demand map for ALL items
	Qualified Demand = Open SO quantity where delivery_date <= today
	Open SO = max(0, qty - delivered_qty) (quantity left to deliver)
	For each Sales Order Item, if delivered_qty >= qty (over-delivered), treat as 0.
	This ensures over-delivery on one SO doesn't reduce open quantity of another SO.
	"""
	from frappe.utils import today

	today_date = today()

	so_rows = frappe.db.sql(
		"""
		SELECT
			soi.item_code,
			SUM(GREATEST(0, soi.qty - IFNULL(soi.delivered_qty, 0))) as so_qty
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


def get_mrq_map_for_mrp():
	"""Get MRQ (Material Request Quantity) map - sum of (qty - ordered_qty) from Material Request Items
	for all items (only Material Requests with status 'Pending' or 'Partially Ordered')
	"""
	# Get Material Requests with status 'Pending' or 'Partially Ordered'
	mrq_rows = frappe.db.sql(
		"""
		SELECT
			mri.item_code,
			SUM(mri.qty - IFNULL(mri.ordered_qty, 0)) as mrq_qty
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


def get_open_po_map_for_mrp():
	"""Get Open PO (Purchase Order) map - sum of (qty - received_qty) from Purchase Order Items
	for all items. If (qty - received_qty) is negative for a particular PO, treat it as 0.
	Only includes submitted Purchase Orders that are not cancelled.
	"""
	# Get all Purchase Order Items with their qty and received_qty
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

	# Calculate open_po for each item
	# For each PO item: if (qty - received_qty) < 0, treat as 0, otherwise use (qty - received_qty)
	open_po_map = {}
	for row in po_rows:
		item_code = row.item_code
		qty = flt(row.qty)
		received_qty = flt(row.received_qty)
		open_qty = max(0, qty - received_qty)  # If negative, treat as 0

		if item_code in open_po_map:
			open_po_map[item_code] += open_qty
		else:
			open_po_map[item_code] = open_qty

	return open_po_map


def build_calculation_breakdown(info, parent_demand_map):
	"""Build detailed calculation breakdown for an item"""
	item_code = info["item_code"]
	buffer_flag = info["buffer_flag"]
	is_buffer = info["is_buffer"]
	sku_type = info.get("sku_type", "N/A")
	tog = info["tog"]
	qualified_demand = info.get("qualified_demand", 0)
	open_so = info["open_so"]
	stock = info["stock"]
	wip = info["wip"]
	open_po = info.get("open_po", 0)
	mrq = info.get("mrq", 0)
	moq = info.get("moq", 0)
	batch_size = info.get("batch_size", 0)
	total_parent_demand = flt(parent_demand_map.get(item_code, 0))
	initial_order_rec = info["initial_order_rec"]
	final_order_rec = info.get("final_order_rec", 0)
	net_order_rec = info.get("net_order_rec", 0)

	lines = []
	lines.append(f"\n  Item: {item_code}")
	lines.append(f"  Type: {buffer_flag}")
	if sku_type and sku_type != "N/A":
		lines.append(f"  SKU Type: {sku_type}")

	if is_buffer:
		lines.append(f"  TOG: {tog}")
		lines.append(f"  Qualified Demand: {qualified_demand}")
		lines.append(f"  Stock: {stock}")
		lines.append(f"  WIP: {wip}")
		lines.append(f"  Open PO: {open_po}")
		lines.append(f"  MRQ: {mrq}")

		if sku_type in ["BOTA", "PTA"]:
			base_calc = tog + qualified_demand - stock - wip - open_po
			lines.append("  Base Calculation: TOG + Qualified Demand - Stock - WIP - Open PO")
			lines.append(f"                    = {tog} + {qualified_demand} - {stock} - {wip} - {open_po}")
			lines.append(f"                    = {base_calc}")
			lines.append(f"  After MRQ: Base - MRQ = {base_calc} - {mrq} = {final_order_rec}")
		else:
			base_calc = tog + qualified_demand - stock - wip
			lines.append("  Base Calculation: TOG + Qualified Demand - Stock - WIP")
			lines.append(f"                    = {tog} + {qualified_demand} - {stock} - {wip}")
			lines.append(f"                    = {base_calc}")
			lines.append(f"  After MRQ: Base - MRQ = {base_calc} - {mrq} = {final_order_rec}")

		# Show MOQ/Batch Size logic
		if final_order_rec <= 0:
			# Base order recommendation is 0 or negative - MOQ/Batch Size not applied
			if moq > 0:
				lines.append(f"  MOQ: {moq} (Not applied - base order rec is {final_order_rec} <= 0)")
			elif batch_size > 0:
				lines.append(
					f"  Batch Size: {batch_size} (Not applied - base order rec is {final_order_rec} <= 0)"
				)
			else:
				lines.append("  No MOQ or Batch Size")
			lines.append(f"  Net Order Recommendation: 0 (Base order rec is {final_order_rec} <= 0)")
		elif moq > 0:
			if moq < final_order_rec:
				lines.append(f"  MOQ: {moq} (MOQ < Order Rec, using Order Rec)")
				lines.append(f"  Net Order Recommendation: {final_order_rec}")
			else:
				lines.append(f"  MOQ: {moq} (MOQ >= Order Rec, using MOQ)")
				lines.append(f"  Net Order Recommendation: {moq}")
		elif batch_size > 0:
			net_calc = math.ceil(final_order_rec / batch_size) * batch_size
			lines.append(f"  Batch Size: {batch_size}")
			lines.append(
				f"  Net Order Recommendation: ceil({final_order_rec} / {batch_size}) × {batch_size} = {net_calc}"
			)
		else:
			lines.append("  No MOQ or Batch Size")
			lines.append(f"  Net Order Recommendation: {final_order_rec}")

		lines.append("  Note: Parent demand ignored for buffer items")

		if len(info["parent_demands"]) > 0:
			lines.append("  Parent Demands (Ignored):")
			for pd in info["parent_demands"]:
				lines.append(
					f"    - From {pd['parent_item']} (BOM: {pd['bom_name']}): {pd['demand_qty']} [IGNORED - {pd['reason']}]"
				)
	else:
		lines.append(f"  Open SO: {open_so}")
		lines.append(f"  Stock: {stock}")
		lines.append(f"  WIP: {wip}")
		lines.append(f"  Open PO: {open_po}")
		lines.append(f"  Total Parent Demand: {total_parent_demand}")

		if total_parent_demand > 0:
			lines.append("  Parent Demands Breakdown:")
			for pd in info["parent_demands"]:
				if pd["applied"]:
					lines.append(
						f"    - From {pd['parent_item']} (BOM: {pd['bom_name']}): {pd['demand_qty']} {pd['reason']}"
					)
				else:
					lines.append(
						f"    - From {pd['parent_item']} (BOM: {pd['bom_name']}): {pd['demand_qty']} [IGNORED - {pd['reason']}]"
					)

		requirement = open_so + total_parent_demand

		if sku_type in ["PTO", "BOTO"]:
			base_calc = requirement - stock - wip - open_po
			lines.append(
				f"  Requirement: Open SO + Parent Demand = {open_so} + {total_parent_demand} = {requirement}"
			)
			lines.append("  Base Calculation: Requirement - Stock - WIP - Open PO")
			lines.append(f"                    = {requirement} - {stock} - {wip} - {open_po}")
			lines.append(f"                    = {base_calc}")
			lines.append(f"  After MRQ: Base - MRQ = {base_calc} - {mrq} = {final_order_rec}")
		else:
			base_calc = requirement - stock - wip
			lines.append(
				f"  Requirement: Open SO + Parent Demand = {open_so} + {total_parent_demand} = {requirement}"
			)
			lines.append("  Base Calculation: Requirement - Stock - WIP")
			lines.append(f"                    = {requirement} - {stock} - {wip}")
			lines.append(f"                    = {base_calc}")
			lines.append(f"  After MRQ: Base - MRQ = {base_calc} - {mrq} = {final_order_rec}")

		# Show MOQ/Batch Size logic
		if final_order_rec <= 0:
			# Base order recommendation is 0 or negative - MOQ/Batch Size not applied
			if moq > 0:
				lines.append(f"  MOQ: {moq} (Not applied - base order rec is {final_order_rec} <= 0)")
			elif batch_size > 0:
				lines.append(
					f"  Batch Size: {batch_size} (Not applied - base order rec is {final_order_rec} <= 0)"
				)
			else:
				lines.append("  No MOQ or Batch Size")
			lines.append(f"  Net Order Recommendation: 0 (Base order rec is {final_order_rec} <= 0)")
		elif moq > 0:
			if moq < final_order_rec:
				lines.append(f"  MOQ: {moq} (MOQ < Order Rec, using Order Rec)")
				lines.append(f"  Net Order Recommendation: {final_order_rec}")
			else:
				lines.append(f"  MOQ: {moq} (MOQ >= Order Rec, using MOQ)")
				lines.append(f"  Net Order Recommendation: {moq}")
		elif batch_size > 0:
			net_calc = math.ceil(final_order_rec / batch_size) * batch_size
			lines.append(f"  Batch Size: {batch_size}")
			lines.append(
				f"  Net Order Recommendation: ceil({final_order_rec} / {batch_size}) × {batch_size} = {net_calc}"
			)
		else:
			lines.append("  No MOQ or Batch Size")
			lines.append(f"  Net Order Recommendation: {final_order_rec}")

	info["calculation_breakdown"] = "\n".join(lines)


def generate_detailed_log(detailed_info, net_order_recommendations):
	"""Generate detailed log with full breakdown for each item"""
	lines = []
	lines.append("\n" + "=" * 100)
	lines.append("MRP ORDER RECOMMENDATIONS - DETAILED BREAKDOWN (NET ORDER RECOMMENDATIONS)")
	lines.append("=" * 100)

	# Show total count of items
	total_items = len(net_order_recommendations)
	items_in_detailed_info = len(detailed_info)
	lines.append(f"\nTotal Items Processed: {total_items}")
	lines.append(f"Items in Detailed Info: {items_in_detailed_info}")
	if total_items != items_in_detailed_info:
		lines.append(f"WARNING: {total_items - items_in_detailed_info} items missing from detailed_info!")

	# Ensure ALL items from net_order_recommendations are in detailed_info
	# Some items might be in net_order_recommendations but not in detailed_info
	for item_code, net_rec in net_order_recommendations.items():
		if item_code not in detailed_info:
			# Item not in detailed_info - add it with basic info
			detailed_info[item_code] = {
				"item_code": item_code,
				"net_order_rec": net_rec,
				"final_order_rec": 0,
				"buffer_flag": "Unknown",
				"parent_demands": [],
				"calculation_breakdown": f"\n  Item: {item_code}\n  Net Order Recommendation: {net_rec}\n  Note: Item not processed in detailed breakdown",
			}

	# Sort by net order recommendation (descending), then by item_code
	sorted_items = sorted(
		detailed_info.items(),
		key=lambda x: (x[1].get("net_order_rec", 0), x[0]),
		reverse=True,
	)

	# First, show summary - include ALL items with net_order_rec > 0 from net_order_recommendations
	lines.append("\n" + "-" * 100)
	lines.append("SUMMARY (Items with Net Order Recommendation > 0)")
	lines.append("-" * 100)

	# Get all items with net_order_rec > 0 from net_order_recommendations (source of truth)
	items_with_net_rec = [
		(item_code, net_rec) for item_code, net_rec in net_order_recommendations.items() if net_rec > 0
	]
	items_with_net_rec.sort(key=lambda x: (x[1], x[0]), reverse=True)

	for item_code, net_rec in items_with_net_rec:
		info = detailed_info.get(item_code, {})
		final_rec = info.get("final_order_rec", 0)
		buffer_flag = info.get("buffer_flag", "Unknown")
		lines.append(f"  {item_code} ({buffer_flag}): Net Order Rec = {net_rec} (Base: {final_rec})")

	# Then show detailed breakdown for ALL items (including those with net_order_rec = 0)
	lines.append("\n" + "=" * 100)
	lines.append("DETAILED BREAKDOWN FOR ALL ITEMS")
	lines.append("=" * 100)

	# Show ALL items from net_order_recommendations (source of truth)
	# Sort all items by net_order_rec (descending), then by item_code
	all_items_sorted = sorted(
		net_order_recommendations.items(),
		key=lambda x: (x[1], x[0]),
		reverse=True,
	)

	for item_code, net_rec in all_items_sorted:
		if item_code in detailed_info:
			info = detailed_info[item_code]
			# Always use calculation_breakdown - it should be built for all items in Step 6
			breakdown = info.get("calculation_breakdown", "")
			if breakdown and breakdown.strip():
				# Use the breakdown if it exists and is not empty
				lines.append(breakdown)
			else:
				# If breakdown is empty, create a basic one
				buffer_flag = info.get("buffer_flag", "Unknown")
				final_rec = info.get("final_order_rec", 0)
				moq = info.get("moq", 0)
				batch_size = info.get("batch_size", 0)
				lines.append(f"\n  Item: {item_code}")
				lines.append(f"  Type: {buffer_flag}")
				lines.append(f"  Base Order Recommendation: {final_rec}")
				lines.append(f"  Net Order Recommendation: {net_rec}")
				if moq > 0:
					lines.append(f"  MOQ: {moq}")
				if batch_size > 0:
					lines.append(f"  Batch Size: {batch_size}")
				lines.append("  Note: Detailed breakdown not built")
		else:
			# Item not in detailed_info - create a minimal breakdown
			lines.append(f"\n  Item: {item_code}")
			lines.append(f"  Net Order Recommendation: {net_rec}")
			lines.append("  Note: Item not in detailed_info")
		lines.append("-" * 100)

	# Also show items with parent demands but zero net order recommendation (for debugging)
	items_with_parent_demand = [
		(item_code, info)
		for item_code, info in sorted_items
		if info["total_parent_demand"] > 0 and info.get("net_order_rec", 0) == 0
	]

	if items_with_parent_demand:
		lines.append("\n" + "=" * 100)
		lines.append("ITEMS WITH PARENT DEMAND BUT ZERO NET ORDER RECOMMENDATION")
		lines.append("=" * 100)
		for item_code, info in items_with_parent_demand:
			lines.append(info["calculation_breakdown"])
			lines.append("-" * 100)

	lines.append("\n" + "=" * 100)

	return "\n".join(lines)

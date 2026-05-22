# Copyright (c) 2026, beetashoke chakraborty and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import flt


class BOMSolver(Document):
	pass


@frappe.whitelist()
def solve_bom():
	"""
	Process all BOMs to:
	1. Remove bom_no from all BOM Item rows
	2. Set do_not_explode = 1 for all BOM Item rows
	3. Handle linked Sales Orders and Sales Invoices by cancelling, updating BOM, then re-submitting
	"""
	results = {
		"total_boms": 0,
		"processed": 0,
		"failed": 0,
		"skipped": 0,
		"errors": [],
		"details": [],
		"processed_list": [],  # List of processed BOMs with details
		"skipped_list": []     # List of skipped BOMs with reasons
	}
	
	try:
		# Get all BOMs
		all_boms = frappe.get_all("BOM", filters={"docstatus": ["!=", 2]}, fields=["name", "item", "docstatus"])
		results["total_boms"] = len(all_boms)
		
		frappe.publish_progress(0, _("Starting BOM processing..."))
		
		for idx, bom_info in enumerate(all_boms):
			bom_name = bom_info["name"]
			bom_item = bom_info["item"]
			bom_docstatus = bom_info["docstatus"]
			
			try:
				frappe.publish_progress(
					(idx + 1) / len(all_boms) * 100,
					_("Processing BOM: {0}").format(bom_name)
				)
				
				# Process this BOM
				bom_result = _process_single_bom(bom_name, bom_item, bom_docstatus)
				results["details"].append(bom_result)
				
				if bom_result["status"] == "success":
					results["processed"] += 1
					results["processed_list"].append({
						"bom": bom_name,
						"item": bom_item,
						"message": bom_result.get("message", "Updated successfully"),
						"linked_sos": bom_result.get("linked_sos", []),
						"linked_sis": bom_result.get("linked_sis", []),
						"cancelled_sos": bom_result.get("cancelled_sos", []),
						"cancelled_sis": bom_result.get("cancelled_sis", []),
						"re_submitted_sos": bom_result.get("re_submitted_sos", []),
						"re_submitted_sis": bom_result.get("re_submitted_sis", []),
						"failed_re_submit_sos": bom_result.get("failed_re_submit_sos", []),
						"failed_re_submit_sis": bom_result.get("failed_re_submit_sis", [])
					})
				elif bom_result["status"] == "skipped":
					results["skipped"] += 1
					results["skipped_list"].append({
						"bom": bom_name,
						"item": bom_item,
						"reason": bom_result.get("message", "Skipped")
					})
				else:
					results["failed"] += 1
					error_msg = bom_result.get('error', 'Unknown error')
					results["errors"].append(f"{bom_name}: {error_msg}")
					
			except Exception as e:
				error_msg = str(e)
				frappe.log_error(
					f"BOM {bom_name} processing failed: {error_msg}",
					"BOM Solver Error"
				)
				results["failed"] += 1
				results["errors"].append(f"{bom_name}: {error_msg[:100]}")
				results["details"].append({
					"bom": bom_name,
					"status": "failed",
					"error": error_msg[:200]
				})
		
		frappe.publish_progress(100, _("BOM processing completed"))
		
		return results
		
	except Exception as e:
		error_msg = str(e)
		frappe.log_error(
			f"Fatal error in solve_bom: {error_msg}",
			"BOM Solver Fatal"
		)
		results["errors"].append(f"Fatal: {error_msg[:100]}")
		return results


def _process_single_bom(bom_name, bom_item, bom_docstatus):
	"""
	Process a single BOM:
	1. Find linked Sales Orders and Sales Invoices
	2. Cancel them if possible
	3. Update BOM Item child table
	4. Submit BOM
	5. Re-submit linked documents
	"""
	result = {
		"bom": bom_name,
		"item": bom_item,
		"status": "pending",
		"linked_sos": [],
		"linked_sis": [],
		"cancelled_sos": [],
		"cancelled_sis": [],
		"error": None
	}
	
	try:
		# Get BOM document
		bom_doc = frappe.get_doc("BOM", bom_name)
		
		# Check if BOM has items
		if not bom_doc.items:
			result["status"] = "skipped"
			result["message"] = "No BOM items found"
			return result
		
		# Find linked Sales Orders and Sales Invoices through item_code
		linked_sos = _find_linked_sales_orders(bom_item)
		linked_sis = _find_linked_sales_invoices(bom_item)
		
		result["linked_sos"] = [so["name"] for so in linked_sos]
		result["linked_sis"] = [si["name"] for si in linked_sis]
		
		# Cancel linked documents if BOM is submitted
		# IMPORTANT: Cancel Sales Invoices FIRST, then Sales Orders
		# because Sales Orders are linked to Sales Invoices
		cancelled_sos = []
		cancelled_sis = []
		
		if bom_docstatus == 1:  # BOM is submitted
			# Step 1: Cancel Sales Invoices FIRST
			for si_info in linked_sis:
				si_name = si_info["name"]
				if si_info["docstatus"] == 1:  # Only cancel submitted SIs
					try:
						si_doc = frappe.get_doc("Sales Invoice", si_name)
						# Check if SI can be cancelled (not paid and no outstanding)
						if si_doc.status == "Unpaid" and si_doc.outstanding_amount == 0:
							si_doc.cancel()
							cancelled_sis.append(si_name)
					except Exception as e:
						# If cancellation fails, log but continue
						error_msg = str(e)
						frappe.log_error(
							f"SI {si_name} cancel failed: {error_msg}",
							"BOM Solver SI Cancel"
						)
			
			# Step 2: Cancel Sales Orders AFTER cancelling linked Sales Invoices
			for so_info in linked_sos:
				so_name = so_info["name"]
				if so_info["docstatus"] == 1:  # Only cancel submitted SOs
					try:
						so_doc = frappe.get_doc("Sales Order", so_name)
						# Check if SO can be cancelled (not delivered/billed)
						if so_doc.status not in ["Completed", "Closed"]:
							# Check if SO has linked Sales Invoices that weren't cancelled
							# Check both Sales Invoice header and Sales Invoice Item
							linked_sis_for_so = frappe.db.sql("""
								SELECT DISTINCT si.name, si.docstatus
								FROM `tabSales Invoice` si
								LEFT JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
								WHERE (si.sales_order = %s OR sii.sales_order = %s)
								AND si.docstatus = 1
							""", (so_name, so_name), as_dict=True)
							
							# Only cancel if no active linked Sales Invoices
							if not linked_sis_for_so:
								so_doc.cancel()
								cancelled_sos.append(so_name)
					except Exception as e:
						# If cancellation fails, log but continue
						error_msg = str(e)
						frappe.log_error(
							f"SO {so_name} cancel failed: {error_msg}",
							"BOM Solver SO Cancel"
						)
		
		result["cancelled_sos"] = cancelled_sos
		result["cancelled_sis"] = cancelled_sis
		
		# Reload BOM document to get latest state
		bom_doc = frappe.get_doc("BOM", bom_name)
		
		# Check if updates are needed before making changes
		needs_update = False
		
		# Check if any BOM items have bom_no set or do_not_explode != 1
		for bom_item_row in bom_doc.items:
			has_bom_no = hasattr(bom_item_row, 'bom_no') and bom_item_row.bom_no
			needs_do_not_explode = False
			if hasattr(bom_item_row, 'do_not_explode'):
				needs_do_not_explode = bom_item_row.do_not_explode != 1
			else:
				# Field might not exist, assume it needs to be set
				needs_do_not_explode = True
			
			if has_bom_no or needs_do_not_explode:
				needs_update = True
				break
		
		changes_made = False
		
		if needs_update:
			# Update via SQL for bom_no removal and do_not_explode (more reliable for bulk updates)
			# Update bom_no to NULL for all items in this BOM
			frappe.db.sql("""
				UPDATE `tabBOM Item`
				SET bom_no = NULL
				WHERE parent = %s AND bom_no IS NOT NULL
			""", (bom_name,))
			
			# Update do_not_explode to 1 for all items in this BOM
			frappe.db.sql("""
				UPDATE `tabBOM Item`
				SET do_not_explode = 1
				WHERE parent = %s AND (do_not_explode IS NULL OR do_not_explode != 1)
			""", (bom_name,))
			
			# Reload the document to reflect SQL changes
			bom_doc.reload()
			changes_made = True
		
		# Save and submit BOM if changes were made
		if changes_made:
			# Save BOM
			bom_doc.save()
			
			# Submit BOM if it was submitted before
			if bom_docstatus == 1:
				bom_doc.reload()
				if bom_doc.docstatus == 0:
					bom_doc.submit()
		
		# IMPORTANT: Re-submit cancelled documents AFTER BOM is updated/submitted
		# This must happen even if no BOM changes were made (in case documents were canceled)
		re_submitted_sos = []
		failed_re_submit_sos = []
		
		if cancelled_sos:
			for so_name in cancelled_sos:
				try:
					so_doc = frappe.get_doc("Sales Order", so_name)
					if so_doc.docstatus == 2:  # Cancelled
						# Reset docstatus to draft
						so_doc.docstatus = 0
						so_doc.save()
						
						# Submit the Sales Order
						so_doc.reload()
						so_doc.submit()
						re_submitted_sos.append(so_name)
				except Exception as e:
					error_msg = str(e)
					failed_re_submit_sos.append(so_name)
					frappe.log_error(
						f"SO {so_name} re-submit failed: {error_msg}",
						"BOM Solver SO Resubmit"
					)
		
		re_submitted_sis = []
		failed_re_submit_sis = []
		
		if cancelled_sis:
			for si_name in cancelled_sis:
				try:
					si_doc = frappe.get_doc("Sales Invoice", si_name)
					if si_doc.docstatus == 2:  # Cancelled
						# Reset docstatus to draft
						si_doc.docstatus = 0
						si_doc.save()
						
						# Submit the Sales Invoice
						si_doc.reload()
						si_doc.submit()
						re_submitted_sis.append(si_name)
				except Exception as e:
					error_msg = str(e)
					failed_re_submit_sis.append(si_name)
					frappe.log_error(
						f"SI {si_name} re-submit failed: {error_msg}",
						"BOM Solver SI Resubmit"
					)
		
		# Update result with re-submission info
		result["re_submitted_sos"] = re_submitted_sos
		result["re_submitted_sis"] = re_submitted_sis
		result["failed_re_submit_sos"] = failed_re_submit_sos
		result["failed_re_submit_sis"] = failed_re_submit_sis
		
		# Set final status and message
		if changes_made:
			result["status"] = "success"
			result["message"] = f"Updated {len(bom_doc.items)} BOM items"
			if re_submitted_sos:
				result["message"] += f", re-submitted {len(re_submitted_sos)} Sales Orders"
			if re_submitted_sis:
				result["message"] += f", re-submitted {len(re_submitted_sis)} Sales Invoices"
			if failed_re_submit_sos or failed_re_submit_sis:
				result["message"] += f" (Warning: {len(failed_re_submit_sos) + len(failed_re_submit_sis)} documents failed to re-submit)"
		elif cancelled_sos or cancelled_sis:
			# Even if no BOM changes, if we canceled documents, we should have re-submitted them
			result["status"] = "success"
			result["message"] = "No BOM changes needed"
			if re_submitted_sos:
				result["message"] += f", re-submitted {len(re_submitted_sos)} Sales Orders"
			if re_submitted_sis:
				result["message"] += f", re-submitted {len(re_submitted_sis)} Sales Invoices"
			if failed_re_submit_sos or failed_re_submit_sis:
				result["message"] += f" (Warning: {len(failed_re_submit_sos) + len(failed_re_submit_sis)} documents failed to re-submit)"
		else:
			result["status"] = "skipped"
			# Provide more detailed skip reason
			skip_reasons = []
			has_bom_no = False
			needs_do_not_explode = False
			
			for bom_item_row in bom_doc.items:
				if hasattr(bom_item_row, 'bom_no') and bom_item_row.bom_no:
					has_bom_no = True
				if hasattr(bom_item_row, 'do_not_explode'):
					if bom_item_row.do_not_explode != 1:
						needs_do_not_explode = True
				else:
					needs_do_not_explode = True
			
			if not has_bom_no and not needs_do_not_explode:
				result["message"] = "No changes needed - bom_no already empty and do_not_explode already set to 1"
			elif not has_bom_no:
				result["message"] = "No changes needed - bom_no already empty (do_not_explode may need manual check)"
			elif not needs_do_not_explode:
				result["message"] = "No changes needed - do_not_explode already set to 1 (bom_no may need manual check)"
			else:
				result["message"] = "No changes detected - may need manual verification"
		
		return result
		
	except Exception as e:
		result["status"] = "failed"
		error_msg = str(e)
		result["error"] = error_msg[:200]  # Truncate for result display
		frappe.log_error(
			f"BOM {bom_name} processing failed: {error_msg}",
			"BOM Solver Error"
		)
		return result


def _find_linked_sales_orders(item_code):
	"""Find all Sales Orders linked to this item (through BOM)"""
	if not item_code:
		return []
	
	# Find Sales Orders that have this item
	sos = frappe.db.sql("""
		SELECT DISTINCT so.name, so.docstatus, so.status
		FROM `tabSales Order` so
		INNER JOIN `tabSales Order Item` soi ON soi.parent = so.name
		WHERE soi.item_code = %s
		AND so.docstatus != 2
	""", (item_code,), as_dict=True)
	
	return sos


def _find_linked_sales_invoices(item_code):
	"""Find all Sales Invoices linked to this item (through BOM)"""
	if not item_code:
		return []
	
	# Find Sales Invoices that have this item
	sis = frappe.db.sql("""
		SELECT DISTINCT si.name, si.docstatus, si.status, si.outstanding_amount
		FROM `tabSales Invoice` si
		INNER JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		WHERE sii.item_code = %s
		AND si.docstatus != 2
	""", (item_code,), as_dict=True)
	
	return sis

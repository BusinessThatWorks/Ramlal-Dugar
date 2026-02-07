#!/usr/bin/env python3
"""
Script to verify SKU type counts in the planning dashboard.
Run this to check how many items are being counted for each SKU type.
"""

import frappe

def calculate_sku_type(buffer_flag, item_type):
	"""Calculate SKU type based on buffer flag and item type"""
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

def verify_sku_counts():
	"""Verify the counts for each SKU type"""
	
	# Get ALL buffer items
	items_data = frappe.db.sql(
		"""
		SELECT
			i.name as item_code,
			i.custom_buffer_flag as buffer_flag,
			i.custom_item_type as item_type,
			i.safety_stock as tog
		FROM
			`tabItem` i
		WHERE
			i.custom_buffer_flag = 'Buffer'
		ORDER BY
			i.custom_item_type, i.name
		""",
		as_dict=1,
	)

	print(f"\n{'='*80}")
	print(f"VERIFICATION OF SKU TYPE COUNTS")
	print(f"{'='*80}")
	print(f"\nTotal Buffer Items Found: {len(items_data)}\n")

	# Count by item_type
	item_type_counts = {}
	for item in items_data:
		item_type = item.get("item_type") or "None"
		item_type_counts[item_type] = item_type_counts.get(item_type, 0) + 1
	
	print("Items by Item Type (from database):")
	print("-" * 80)
	for item_type, count in sorted(item_type_counts.items()):
		print(f"  {item_type}: {count} items")
	
	# Calculate SKU types
	sku_type_counts = {}
	sku_type_details = {}
	target_sku_types = ["FGMTA", "SFGMTA", "PTA"]
	
	for item in items_data:
		item_code = item.item_code
		buffer_flag = item.get("buffer_flag") or "Buffer"
		item_type = item.get("item_type")
		
		sku_type = calculate_sku_type(buffer_flag, item_type)
		
		if sku_type:
			if sku_type not in sku_type_counts:
				sku_type_counts[sku_type] = 0
				sku_type_details[sku_type] = []
			sku_type_counts[sku_type] += 1
			sku_type_details[sku_type].append({
				"item_code": item_code,
				"item_type": item_type,
				"buffer_flag": buffer_flag
			})
	
	print(f"\n{'='*80}")
	print("Items by Calculated SKU Type:")
	print("-" * 80)
	for sku_type in sorted(sku_type_counts.keys()):
		count = sku_type_counts[sku_type]
		print(f"  {sku_type}: {count} items")
	
	print(f"\n{'='*80}")
	print("Target SKU Types (shown in dashboard):")
	print("-" * 80)
	for sku_type in target_sku_types:
		count = sku_type_counts.get(sku_type, 0)
		print(f"  {sku_type}: {count} items")
		if count > 0 and count <= 20:
			print(f"    Items:")
			for detail in sku_type_details[sku_type]:
				print(f"      - {detail['item_code']} (item_type: {detail['item_type']}, buffer_flag: {detail['buffer_flag']})")
		elif count > 20:
			print(f"    First 10 items:")
			for detail in sku_type_details[sku_type][:10]:
				print(f"      - {detail['item_code']} (item_type: {detail['item_type']}, buffer_flag: {detail['buffer_flag']})")
			print(f"    ... and {count - 10} more")
	
	# Show items that don't map to target SKU types
	unmapped_items = []
	for item in items_data:
		item_code = item.item_code
		buffer_flag = item.get("buffer_flag") or "Buffer"
		item_type = item.get("item_type")
		sku_type = calculate_sku_type(buffer_flag, item_type)
		
		if not sku_type or sku_type not in target_sku_types:
			unmapped_items.append({
				"item_code": item_code,
				"item_type": item_type,
				"buffer_flag": buffer_flag,
				"calculated_sku_type": sku_type
			})
	
	if unmapped_items:
		print(f"\n{'='*80}")
		print(f"Items NOT included in dashboard (not FGMTA/SFGMTA/PTA): {len(unmapped_items)}")
		print("-" * 80)
		for item in unmapped_items[:20]:
			print(f"  - {item['item_code']}: item_type='{item['item_type']}', buffer_flag='{item['buffer_flag']}', calculated_sku_type='{item['calculated_sku_type']}'")
		if len(unmapped_items) > 20:
			print(f"  ... and {len(unmapped_items) - 20} more")
	
	print(f"\n{'='*80}\n")

if __name__ == "__main__":
	frappe.init(site='your-site-name')  # Update with your site name
	frappe.connect()
	verify_sku_counts()
	frappe.destroy()


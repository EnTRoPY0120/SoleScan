# Use immutable comparison revisions for retailer verification

After a shopper clears a retailer verification screen, SoleScan creates a new comparison revision that reruns only that retailer. Offers and retailer outcomes from every other source are copied with their original observation times. The new revision records its source comparison, selected retailer, and retailer-specific attempt count.

This avoids implying that unchanged stores were checked again, preserves the evidence behind the prior comparison, and keeps verification retries auditable. It costs additional database rows and revision metadata, but those costs are preferable to silently mixing observations from different times or rerunning all retailers after one clearance.

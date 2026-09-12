---
id: mapping-validation-basics
version: 1.2
module: mapping_validator
authority: deterministic
status: approved
---
# Mapping validation rules

## Required workbook structure
Pass when the workbook contains a sheet named Source to Target. Fail when that sheet is missing.

## Required mapping columns
Pass when Map Group ID, Source Object Name, Source Object ID, Source Attribute Name, Source Attribute ID, Target Object Name, and Target Attribute Name are present. Fail when any required column is missing.

## Non-empty map group
Pass when every mapping row has a non-empty Map Group ID. Blank values are deterministic errors because the mapping cannot be reliably grouped.

## Non-empty source object
Pass when each mapping row identifies a source object and source object ID. Blank Source Object Name or Source Object ID values are deterministic errors because SQL generation cannot identify its input.

## Non-empty source attribute
Pass when each mapping row identifies a source attribute and source attribute ID. Blank Source Attribute Name or Source Attribute ID values are deterministic errors because the source mapping cannot be identified reliably.

## Non-empty target object
Pass when each mapping row identifies a target object. A blank Target Object Name is a deterministic error because the destination cannot be generated.

## Non-empty target attribute
Pass when each mapping row identifies a target attribute. A blank Target Attribute Name is a deterministic error because the destination column cannot be generated.

## Consistent target per group
Pass when all rows in a map group point to one target table. More than one target table is a warning requiring analyst review.

## Duplicate source mapping
Pass when a source object and source attribute occur once per map group. Duplicate source attributes are warnings because they may produce repeated expressions.

## Duplicate target mapping
Pass when a target object and target attribute occur once per map group. Duplicate target attributes are warnings because they may overwrite one another.

## Trimmed identifiers
Pass when identifiers do not contain leading or trailing whitespace. Whitespace is normalized for blank checks, but the source workbook should be corrected.

## Data processing rule reference
Pass when a Data Processing Rule value is empty or matches an approved rule reference. Unknown rule references must remain warnings or errors and must never be approved by an LLM.

## Active mapping rows
Pass when inactive rows are explicitly marked and do not replace an active mapping. Conflicting active and inactive versions require analyst review.

## Map group cardinality
Pass when at least one non-empty map group exists for a non-empty workbook. A workbook with no usable map groups fails structural validation.

## LLM boundary
The language model may explain deterministic findings and identify relevant approved rules. It may not change the pass or fail result, create a rule, or approve a warning.

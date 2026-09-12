---
id: sql-generation-basics
version: 1.0
module: sql_generator
authority: deterministic
status: approved
---
# SQL generation rules

## Deterministic output
Generated SQL must be checked by the SQL audit, join validator, parameter resolver, and column pruner after any advisory explanation. A generated artifact is reviewable output, not approval to deploy.

## Multiple source tables
When one target attribute names multiple source objects, keep a `NULL` expression with a TODO comment instead of guessing the source table. Confirm the intended source object and join path with the BA, then regenerate the SQL.

## Missing DPR rule
When a mapping row is marked as a DPR source but has no Data Processing Rule, emit a TODO for the target attribute. Do not infer a transformation or silently omit the target column.

## Unknown DPR rule
When a Data Processing Rule does not match an approved DPR definition, emit a TODO for the target attribute. Confirm the rule name and approved process type before changing the generated expression.

## Narrative transformation note
When a transform note describes business logic but does not contain executable SQL syntax, emit a `NULL` TODO expression. Convert the narrative into an approved SQL expression and verify its source attributes before regeneration.

## Missing join reference
When a source table appears in Source to Target but is absent from the selected Map Group Code join instructions, retain the deterministic warning and add a TODO for join review. Do not invent a join condition or approve the SQL automatically.

## TODO review boundary
Every TODO and warning must remain visible in the SQL output and advisory report. Ollama may explain the approved remediation guidance, but it may not resolve, remove, or approve a TODO.

## Advisory boundary
The language model may explain warnings and retrieve relevant SQL rules. It may not directly approve or write an unchecked SQL artifact.

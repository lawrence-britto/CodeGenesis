---
id: parity-comparison-basics
version: 1.0
module: prod_parity
authority: deterministic
status: approved
---
# Production parity rules

## Comparison authority
Line differences, added or removed tables, columns, and structural differences must come from the deterministic parity comparison engine.

## Advisory boundary
The language model may summarize a detected difference using these approved rules. It may not declare two SQL artifacts identical.

## Risk interpretation
Semantic changes require review even when no deterministic dangerous pattern is present. Changes to SQL filtering or JOIN behavior, shell commands, Python functions, or YAML runtime settings must be called out explicitly. HIGH and CRITICAL findings are high risk; the language model may explain their impact but may not lower their severity or approve the change.

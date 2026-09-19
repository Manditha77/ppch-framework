# PPCH Live Demo — Before vs After

## Cognitive Complexity (real SonarScanner measurement, PricingEngine.java)

- Before: **35.0**
- After:  **31.0**
- Change: **-4.0** (-11.4%)

## Predicted Risk (Analyze layer, same trained models throughout)

- Before: risk_score = **0.302** -> action = `no_intervention`
- After:  risk_score = **0.301** -> action = `no_intervention`

## Refactoring suggestion (Act layer)

A refactoring suggestion WAS generated for the BEFORE version, targeting `calculateFinalPrice` (approximate complexity 28.0).
- Triggered by: Act layer: measured complexity_before 35.0 > per-method threshold 15.0
- Suggested extraction: lines 21-29 of PricingEngine.java
- Inferred parameters: ['customer', 'discount', 'order']
- Suggested method name: `calculateFinalPriceExtracted`
- Note: risk_score (0.302) was below the Analyze layer's own warning threshold; this suggestion was triggered by the measured complexity alone, independent of the ML prediction.

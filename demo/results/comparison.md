# PPCH Live Demo — Before vs After

## Cognitive Complexity (real SonarScanner measurement, PricingEngine.java)

- Before: **35.0**
- After:  **31.0**
- Change: **-4.0** (-11.4%)

## Predicted Risk (Analyze layer, same trained models throughout)

- Before: risk_score = **0.806** -> action = `complexity_warning_and_refactoring_review`
- After:  risk_score = **0.808** -> action = `complexity_warning_and_refactoring_review`

## Refactoring suggestion (Act layer)

A refactoring suggestion WAS generated for the BEFORE version, targeting `calculateFinalPrice` (approximate complexity 29.0).
- Triggered by: Analyze layer: risk_score 0.806 >= warning threshold
- Triggered by: Act layer: measured complexity_before 35.0 > per-method threshold 15.0
- Suggested extraction: lines 21-29 of PricingEngine.java
- Inferred parameters: ['customer', 'discount', 'order']
- Suggested method name: `calculateFinalPriceExtracted`

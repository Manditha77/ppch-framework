package com.demo.pricing;

public class PricingEngine {

    /**
     * Deliberately complex: this method concentrates its cognitive complexity
     * into the discount-code handling block below, so it is a realistic
     * candidate for an "Extract Method" refactoring - the tier-discount logic
     * above it is comparatively simple by contrast.
     */
    public double calculateFinalPrice(Customer customer, Order order, String couponCode, boolean isHoliday) {
        double basePrice = order.getSubtotal();
        double discount = baseDiscountForTier(customer, order, isHoliday);

        if (couponCode != null && !couponCode.isEmpty()) {
            if (couponCode.equals("SAVE10")) {
                discount = discount + 0.10;
            } else if (couponCode.equals("SAVE20")) {
                discount = discount + 0.20;
            } else if (couponCode.startsWith("VIP")) {
                if (customer.getTier() == CustomerTier.GOLD) {
                    if (order.getItemCount() > 5) {
                        discount = discount + 0.15;
                    } else {
                        discount = discount + 0.10;
                    }
                } else if (customer.getTier() == CustomerTier.SILVER) {
                    discount = discount + 0.05;
                }
            } else if (couponCode.startsWith("SEASONAL")) {
                if (isHoliday) {
                    if (order.getItemCount() > 10) {
                        discount = discount + 0.12;
                    } else {
                        discount = discount + 0.08;
                    }
                } else {
                    discount = discount + 0.02;
                }
            }
        }

        if (discount > 0.5) {
            discount = 0.5;
        }

        double finalPrice = basePrice * (1 - discount);

        if (finalPrice < 0) {
            finalPrice = 0;
        }

        return finalPrice;
    }

    private double baseDiscountForTier(Customer customer, Order order, boolean isHoliday) {
        if (customer.getTier() == CustomerTier.GOLD) {
            return order.getItemCount() > 10 ? 0.20 : 0.10;
        } else if (customer.getTier() == CustomerTier.SILVER) {
            return order.getItemCount() > 10 ? 0.10 : 0.05;
        }
        return isHoliday ? 0.05 : 0.0;
    }

    public double getTaxRate(String region) {
        if (region.equals("EU")) {
            return 0.20;
        }
        return 0.08;
    }

    public String formatCurrency(double amount) {
        return String.format("$%.2f", amount);
    }
}

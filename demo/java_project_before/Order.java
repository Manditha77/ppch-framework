package com.demo.pricing;

public class Order {

    private final double subtotal;
    private final int itemCount;

    public Order(double subtotal, int itemCount) {
        this.subtotal = subtotal;
        this.itemCount = itemCount;
    }

    public double getSubtotal() {
        return subtotal;
    }

    public int getItemCount() {
        return itemCount;
    }
}

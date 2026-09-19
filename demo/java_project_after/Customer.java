package com.demo.pricing;

public class Customer {

    private final String name;
    private final CustomerTier tier;

    public Customer(String name, CustomerTier tier) {
        this.name = name;
        this.tier = tier;
    }

    public String getName() {
        return name;
    }

    public CustomerTier getTier() {
        return tier;
    }
}

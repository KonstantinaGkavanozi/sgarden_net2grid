package com.sgarden.dto;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.Map;

@Data
@AllArgsConstructor
public class ProductStatsResponse {
    private long totalCount;
    private Double averagePrice;
    private Double minPrice;
    private Double maxPrice;
    private Map<String, Long> categoryCount;
}

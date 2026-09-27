#pragma once
#include <stdint.h>

// Recovery is based on the endpoint that was actually hit, not the midpoint
// of the already-updated position (which is ambiguous for a two-position range).
constexpr uint16_t inward_from_boundary(uint16_t start, uint16_t end, uint16_t boundary) {
    return start >= end ? start : (boundary == start ? start + 1 : end - 1);
}
static_assert(inward_from_boundary(0,1,0) == 1, "Lower stop must retain inward step in a two-item list");
static_assert(inward_from_boundary(0,1,1) == 0, "Upper stop must retain inward step in a two-item list");
static_assert(inward_from_boundary(0,0,0) == 0, "Single item cannot generate a step");
static_assert(inward_from_boundary(0,2,0) == 1 && inward_from_boundary(0,2,2) == 1, "Transport returns to neutral");
static_assert(inward_from_boundary(10,20,10) == 11 && inward_from_boundary(10,20,20) == 19, "Nonzero native bounds remain valid");

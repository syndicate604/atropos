# GRPO Training Results Comparison

## Summary

| Metric | Baseline (Base Model) | Trained (200 steps) | Improvement |
|--------|----------------------|---------------------|-------------|
| **Pass Rate** | 1/8 (12.5%) | **3/8 (37.5%)** | **+25%** |
| **Tasks Passed** | 1 | **3** | **+2 tasks** |
| **Improvement Factor** | 1x | **3x** | **200% gain** |

## Task-by-Task Breakdown

### ✅ PASSED Tasks (3/8)

| Task | Baseline | Trained | Status | Notes |
|------|----------|---------|--------|-------|
| **sqli-001** | ✅ PASS | ✅ PASS | Maintained | Parameterized query with LIKE |
| **path-001** | ❌ FAIL | ✅ **PASS** | **NEW!** | Learned os.path.basename() |
| **sqli-002** | ❌ FAIL | ✅ **PASS** | **NEW!** | Learned isdigit() validation |

### ❌ FAILED Tasks (5/8)

| Task | Baseline | Trained | Failure Reason | Model Attempt |
|------|----------|---------|----------------|---------------|
| **cmd-001** | ❌ FAIL | ❌ FAIL | regression_test_failure | Changed to list but left shell=True (incomplete) |
| **idor-001** | ❌ FAIL | ❌ FAIL | regression_test_failure | Wrong placement (replaced init_db instead of adding check) |
| **xss-001** | ❌ FAIL | ❌ FAIL | regression_test_failure | Escaped in wrong location (body tag not h1) |
| **xss-002** | ❌ FAIL | ❌ FAIL | patch_ineffective | Added f-string to wrong line, didn't escape |
| **trivial-001** | ❌ FAIL | ❌ FAIL | patch_apply_malformed | Nonsensical patch (creates recursion) |

## What the Model Learned

### ✅ Successfully Learned:
1. **Path Traversal (path-001):** Use `os.path.basename()` to strip directory separators
2. **SQL Injection validation (sqli-002):** Use `isdigit()` to validate before query

### ⚠️ Partial Understanding (Close but Wrong):
1. **Command Injection (cmd-001):** Knows to use list args, but forgot to remove `shell=True`
2. **XSS (xss-001):** Knows to use escape(), but wrong placement
3. **IDOR (idor-001):** Knows to check permissions, but wrong code structure

### ❌ Still Struggling:
1. **XSS stored (xss-002):** Doesn't understand where to escape
2. **Trivial (trivial-001):** Generates nonsensical patches

## Training Effectiveness Analysis

**What Worked:**
- ✅ Model learned 2 new security patterns (path traversal, input validation)
- ✅ 3x improvement from baseline (12.5% → 37.5%)
- ✅ Clean test infrastructure provided good training signal
- ✅ GRPO successfully amplified successful patterns

**What Needs Improvement:**
- ⚠️ 200 steps might not be enough for harder patterns (XSS, IDOR)
- ⚠️ Learning rate (1e-6) very conservative, might benefit from 5e-6
- ⚠️ Model still makes structural mistakes (wrong line placement)

## Specific Examples

### ✅ path-001 (NEW PASS!)

**Baseline:** Failed with patch_ineffective (route line no-op)

**Trained Model Patch:**
```diff
-        return send_file(filepath)
+        return send_file(os.path.join("/workspace/files", os.path.basename(filename)))
```
**Result:** ✅ PASSED - Correctly uses basename() to prevent path traversal

---

### ✅ sqli-002 (NEW PASS!)

**Baseline:** Failed with backwards logic (`if not user_id or user_id.isdigit()`)

**Trained Model Patch:**
```diff
-    if not user_id:
+    if not user_id or not user_id.isdigit():
         return jsonify({"users": []})
```
**Result:** ✅ PASSED - Correctly validates input is digits before SQL query

---

### ⚠️ cmd-001 (Still Failing - Partial Fix)

**Trained Model Patch:**
```diff
-        f"echo {message}",
+        [\"echo\", message],
         shell=True,  ← FORGOT TO REMOVE THIS!
```
**Result:** ❌ regression_test_failure - Incomplete fix (needs to remove shell=True)

---

## Conclusion

**GRPO training was successful!** The model:
- ✅ Learned 2 new vulnerability patterns in 200 steps
- ✅ Tripled its pass rate from baseline
- ✅ Shows understanding of security concepts (validates input, sanitizes paths)
- ⚠️ Still struggles with complex patterns (XSS escaping, IDOR logic)

**Next Steps:**
1. **Short term:** Longer training (500-1000 steps) to learn harder patterns
2. **Medium term:** Increase learning rate to 5e-6 for faster convergence
3. **Long term:** Task-specific hints for XSS/IDOR or curriculum learning

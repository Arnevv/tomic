diff --git a//dev/null b/AGENTS.md
index 0000000..415c09b 100644
--- a//dev/null
+++ b/AGENTS.md
@@ -0,0 +1,16 @@
+# Repository Guidelines for TOMIC
+
+This file provides instructions for modifying the code in this repository.
+
+## Key resources
+
+* **Always** consult the latest IBKR API documentation for Python at <https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc> before implementing changes.
+* Refer to the book *Option Trader's Hedge Fund* (available in the project documents) for option strategies and related questions.
+
+## Development rules
+
+* Avoid regressions: modify only the files requested in the task and leave other code untouched.
+* Keep the existing structure and style of the scripts. They are simple standalone Python files that use the IB API.
+* The project currently has no automated test suite. Check that Python files compile without errors using `python -m py_compile file.py` where possible.
+* Commit changes with clear messages and verify the working tree is clean before opening a pull request.
+

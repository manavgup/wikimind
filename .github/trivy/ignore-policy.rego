# Grace period for freshly published advisories.
#
# The Docker workflow fails the build on any HIGH/CRITICAL CVE with an
# available fix. Advisories are published daily, so a PR that was green
# at review time can go red at merge time on a finding unrelated to its
# changes — this happened three times in four days (#833, #835, and the
# post-#833 deploy that was skipped on main).
#
# This policy ignores HIGH vulnerabilities published within the last
# 7 days, giving a window to bump the dependency in an orderly PR
# instead of freezing every in-flight merge. After 7 days the scan
# fails as before, so nothing can be ignored indefinitely.
#
# CRITICAL vulnerabilities are never ignored — they block immediately.
#
# Findings with no parseable PublishedDate fail closed (not ignored).

package trivy

import rego.v1

default ignore := false

ignore if {
	input.Severity == "HIGH"
	published := time.parse_rfc3339_ns(input.PublishedDate)
	time.now_ns() - published < 7 * 24 * 60 * 60 * 1000000000
}

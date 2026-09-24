package profile

import (
	"strings"
	"testing"
)

const validReleaseProfile = `{
  "schemaVersion": 1,
  "version": "0.3.0",
  "validation": {"status":"passed","completedAt":"2026-09-24T00:00:00Z","evidenceUrl":"https://github.com/xiongweilin/aios/actions/runs/123"},
  "compatibility": {"worldRuntimeProtocol":"1.0","semanticLanguage":"1.0","personalWorldContract":"1.0","domainControllerContract":"1.0"},
  "components": [{"id":"agency-console","sourceRepository":"xiongweilin/agency-console","version":"1.2.0","releaseTag":"v1.2.0","artifactUrl":"https://github.com/xiongweilin/agency-console/releases/download/v1.2.0/agency-console.zip","sha256":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}]
}`

func TestParseReleaseProfileAcceptsPinnedVerifiedProfile(t *testing.T) {
	if _, err := ParseReleaseProfile([]byte(validReleaseProfile)); err != nil {
		t.Fatalf("ParseReleaseProfile() error = %v", err)
	}
}

func TestParseReleaseProfileRejectsMutableOrUnverifiableArtifacts(t *testing.T) {
	cases := []struct {
		name string
		edit func(string) string
	}{
		{name: "latest URL", edit: func(s string) string {
			return strings.Replace(s, "v1.2.0/agency-console.zip", "latest/agency-console.zip", 1)
		}},
		{name: "bad digest", edit: func(s string) string {
			return strings.Replace(s, "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "bad", 1)
		}},
		{name: "missing validation", edit: func(s string) string { return strings.Replace(s, `"status":"passed"`, `"status":"pending"`, 1) }},
		{name: "wrong repository", edit: func(s string) string {
			return strings.Replace(s, "xiongweilin/agency-console/releases", "someone-else/agency-console/releases", 1)
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := ParseReleaseProfile([]byte(tc.edit(validReleaseProfile))); err == nil {
				t.Fatal("ParseReleaseProfile() unexpectedly accepted invalid profile")
			}
		})
	}
}

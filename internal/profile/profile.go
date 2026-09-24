package profile

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"regexp"
	"strings"
	"time"
)

// ReleaseProfile is the immutable, compatibility-tested composition installed by AIOS.
// Source/version/digest identify each artifact's owner and lineage; validation records
// the evidence that permits the profile to be used for install or update.
type ReleaseProfile struct {
	SchemaVersion int                `json:"schemaVersion"`
	Version       string             `json:"version"`
	Validated     ProfileValidation  `json:"validation"`
	Compatibility map[string]string  `json:"compatibility"`
	Components    []ProfileComponent `json:"components"`
}

type ProfileValidation struct {
	Status      string `json:"status"`
	CompletedAt string `json:"completedAt"`
	EvidenceURL string `json:"evidenceUrl"`
}

type ProfileComponent struct {
	ID               string `json:"id"`
	SourceRepository string `json:"sourceRepository"`
	Version          string `json:"version"`
	ReleaseTag       string `json:"releaseTag"`
	ArtifactURL      string `json:"artifactUrl"`
	SHA256           string `json:"sha256"`
}

var (
	profileVersionPattern = regexp.MustCompile(`^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$`)
	profileIDPattern      = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)
	sha256Pattern         = regexp.MustCompile(`^[a-fA-F0-9]{64}$`)
)

var requiredCompatibilityContracts = []string{
	"worldRuntimeProtocol",
	"semanticLanguage",
	"personalWorldContract",
	"domainControllerContract",
}

// ParseReleaseProfile rejects mutable/latest URLs, incomplete ownership lineage,
// invalid hashes, and profiles without recorded compatibility-test evidence.
func ParseReleaseProfile(data []byte) (ReleaseProfile, error) {
	var profile ReleaseProfile
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&profile); err != nil {
		return profile, fmt.Errorf("decode AIOS release profile: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return profile, fmt.Errorf("release profile contains trailing JSON")
		}
		return profile, fmt.Errorf("release profile has trailing content: %w", err)
	}
	if profile.SchemaVersion != 1 {
		return profile, fmt.Errorf("unsupported release profile schema %d", profile.SchemaVersion)
	}
	if !profileVersionPattern.MatchString(profile.Version) {
		return profile, fmt.Errorf("invalid AIOS profile version %q", profile.Version)
	}
	if profile.Validated.Status != "passed" {
		return profile, fmt.Errorf("release profile has no passing compatibility validation")
	}
	if _, err := time.Parse(time.RFC3339, profile.Validated.CompletedAt); err != nil {
		return profile, fmt.Errorf("invalid validation completion time: %w", err)
	}
	if err := validateGitHubURL(profile.Validated.EvidenceURL); err != nil {
		return profile, fmt.Errorf("invalid validation evidence URL: %w", err)
	}
	for _, key := range requiredCompatibilityContracts {
		if strings.TrimSpace(profile.Compatibility[key]) == "" {
			return profile, fmt.Errorf("compatibility contract %q is missing", key)
		}
	}
	if len(profile.Components) == 0 {
		return profile, fmt.Errorf("release profile contains no components")
	}
	seen := make(map[string]bool, len(profile.Components))
	for _, component := range profile.Components {
		if !profileIDPattern.MatchString(component.ID) || seen[component.ID] {
			return profile, fmt.Errorf("invalid or duplicate component id %q", component.ID)
		}
		seen[component.ID] = true
		if !profileVersionPattern.MatchString(component.Version) || !profileVersionPattern.MatchString(component.ReleaseTag) {
			return profile, fmt.Errorf("component %q has an invalid pinned version or release tag", component.ID)
		}
		parts := strings.Split(component.SourceRepository, "/")
		if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
			return profile, fmt.Errorf("component %q has an invalid source repository", component.ID)
		}
		if !sha256Pattern.MatchString(component.SHA256) {
			return profile, fmt.Errorf("component %q has an invalid SHA-256 digest", component.ID)
		}
		if err := validateGitHubArtifactURL(component.ArtifactURL, component.SourceRepository, component.ReleaseTag); err != nil {
			return profile, fmt.Errorf("component %q artifact URL: %w", component.ID, err)
		}
	}
	return profile, nil
}

func validateGitHubArtifactURL(raw, repository, releaseTag string) error {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.Host != "github.com" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return fmt.Errorf("must be a direct HTTPS GitHub release URL")
	}
	prefix := "/" + repository + "/releases/download/" + releaseTag + "/"
	if !strings.HasPrefix(u.Path, prefix) || strings.TrimPrefix(u.Path, prefix) == "" {
		return fmt.Errorf("must point to the pinned release of %s", repository)
	}
	return nil
}

func validateGitHubURL(raw string) error {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.Host != "github.com" || u.User != nil || u.Path == "" {
		return fmt.Errorf("must be an HTTPS GitHub evidence URL")
	}
	return nil
}

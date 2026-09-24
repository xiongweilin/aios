package main

import (
	"fmt"
	"os"

	"github.com/xiongweilin/aios/internal/profile"
)

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: verify-profile <manifest.json>")
		os.Exit(2)
	}
	data, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	parsed, err := profile.ParseReleaseProfile(data)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	fmt.Printf("AIOS profile %s: %d pinned component artifacts; compatibility evidence %s\n", parsed.Version, len(parsed.Components), parsed.Validated.EvidenceURL)
}

//go:build windows && product

package main

import (
	"fmt"
	"os"
	"path/filepath"
)

func aiosHome() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("resolve user home: %w", err)
	}
	if home == "" {
		return "", fmt.Errorf("user home directory is empty")
	}
	return filepath.Join(home, ".aios"), nil
}

func ensureAIOSHome() error {
	root, err := aiosHome()
	if err != nil {
		return err
	}
	for _, relative := range []string{
		"config", "state", "data", "logs", "components",
		"domains", "domains/autonomous-development", "domains/administrative",
	} {
		if err := os.MkdirAll(filepath.Join(root, relative), 0700); err != nil {
			return fmt.Errorf("create AIOS directory %s: %w", relative, err)
		}
	}
	return nil
}

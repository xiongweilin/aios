//go:build windows && !product

package main

import (
	_ "embed"
	"fmt"
	"os"
)

//go:embed ui.ps1
var selectorScript string

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		if err := showSelector(selectorScript); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if err := execute(args[0], args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

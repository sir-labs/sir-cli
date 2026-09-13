package main

import (
	"context"
	"os"

	"github.com/docker/docker/client"
	"github.com/spf13/cobra"

	"sir/internal/html"
	"sir/internal/styles"
)

func htmlCmd() *cobra.Command {
	var o html.AddOptions

	withDocker := func(fn func(ctx context.Context, cli *client.Client) error) {
		cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
		if err == nil {
			defer cli.Close()
			err = fn(context.Background(), cli)
		}
		if err != nil {
			styles.CRed.Printf("  Error: %v\n", err)
			os.Exit(1)
		}
	}

	c := &cobra.Command{
		Use:   "html",
		Short: "Publish folders of HTML files as <name>.sir-labs.com sites",
	}

	add := &cobra.Command{
		Use:     "add <path> <name>",
		Short:   "Serve a folder at <name>.<domain> (read-only)",
		Args:    cobra.ExactArgs(2),
		Example: "  sir html add ~/Obsidian/MASTER_DEGREE/MCPE/Thesis thesis2",
		Run: func(cmd *cobra.Command, args []string) {
			o.Path, o.Name = args[0], args[1]
			withDocker(func(ctx context.Context, cli *client.Client) error {
				url, err := html.Add(ctx, cli, o)
				if err == nil {
					styles.CGreen.Printf("  ✓ %s → %s\n", o.Name, url)
				}
				return err
			})
		},
	}
	f := add.Flags()
	f.StringVar(&o.Host, "host", "", "full hostname (default <name>.<domain>)")
	f.StringVar(&o.Title, "title", "", "index page title (default <name>)")
	f.StringVar(&o.Domain, "domain", "sir-labs.com", "base domain")
	f.StringVar(&o.Network, "network", "sir-server_sir-net", "docker network sir-watcher proxies")

	c.AddCommand(add,
		&cobra.Command{
			Use:     "rm <name>",
			Aliases: []string{"remove"},
			Short:   "Stop serving a site",
			Args:    cobra.ExactArgs(1),
			Run: func(cmd *cobra.Command, args []string) {
				withDocker(func(ctx context.Context, cli *client.Client) error {
					err := html.Remove(ctx, cli, args[0])
					if err == nil {
						styles.CGreen.Printf("  ✓ removed %s\n", args[0])
					}
					return err
				})
			},
		},
		&cobra.Command{
			Use:     "ls",
			Aliases: []string{"list"},
			Short:   "List served sites",
			Args:    cobra.NoArgs,
			Run: func(cmd *cobra.Command, args []string) {
				withDocker(func(ctx context.Context, cli *client.Client) error {
					return html.List(ctx, cli, os.Stdout)
				})
			},
		},
	)
	return c
}

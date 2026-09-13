// Package html publishes local folders of HTML files as <name>.<domain> sites.
// Each site is one container carrying sir-watcher's proxy.* labels; the
// container labels are the only registry, so there is no state file to drift.
package html

import (
	"context"
	_ "embed"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/api/types/image"
	"github.com/docker/docker/api/types/mount"
	"github.com/docker/docker/client"
	"github.com/docker/docker/errdefs"
	"github.com/jedib0t/go-pretty/v6/table"
)

//go:embed server.py
var serverPy string

const (
	Image  = "python:3.13-alpine"
	prefix = "sir-html-"
	label  = "sir.html"
)

var validName = regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)

type AddOptions struct {
	Name, Path, Host, Title, Domain, Network string
}

func Add(ctx context.Context, cli *client.Client, o AddOptions) (string, error) {
	if !validName.MatchString(o.Name) {
		return "", fmt.Errorf("name %q must be a DNS label (a-z, 0-9, -)", o.Name)
	}
	path, err := filepath.Abs(o.Path)
	if err != nil {
		return "", err
	}
	if info, err := os.Stat(path); err != nil || !info.IsDir() {
		return "", fmt.Errorf("%s is not a directory", path)
	}
	if o.Host == "" {
		o.Host = o.Name + "." + o.Domain
	}
	if o.Title == "" {
		o.Title = o.Name
	}
	// sir-watcher silently picks one container per host, so a clash would flap a live site.
	taken, err := cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filters.NewArgs(filters.Arg("label", "proxy.host="+o.Host)),
	})
	if err != nil {
		return "", err
	}
	if len(taken) > 0 {
		return "", fmt.Errorf("%s is already served by %s", o.Host, strings.TrimPrefix(taken[0].Names[0], "/"))
	}
	if err := ensureImage(ctx, cli); err != nil {
		return "", err
	}

	cfg := &container.Config{
		Image: Image,
		Cmd:   []string{"python", "-c", serverPy},
		Env:   []string{"MODE=content", "TITLE=" + o.Title},
		Labels: map[string]string{
			"proxy.enable":  "true",
			"proxy.host":    o.Host,
			"proxy.port":    "80",
			label:           "true",
			label + ".path": path,
		},
		Healthcheck: &container.HealthConfig{
			Test:        []string{"CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1/').read()"},
			Interval:    10 * time.Second,
			Timeout:     3 * time.Second,
			Retries:     5,
			StartPeriod: 5 * time.Second,
		},
	}
	host := &container.HostConfig{
		Mounts:        []mount.Mount{{Type: mount.TypeBind, Source: path, Target: "/srv/html", ReadOnly: true}},
		RestartPolicy: container.RestartPolicy{Name: container.RestartPolicyUnlessStopped},
		NetworkMode:   container.NetworkMode(o.Network),
	}
	resp, err := cli.ContainerCreate(ctx, cfg, host, nil, nil, prefix+o.Name)
	if err != nil {
		return "", err
	}
	if err := cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
		_ = cli.ContainerRemove(ctx, resp.ID, container.RemoveOptions{Force: true})
		return "", err
	}
	return "https://" + o.Host, nil
}

func ensureImage(ctx context.Context, cli *client.Client) error {
	if _, err := cli.ImageInspect(ctx, Image); err == nil {
		return nil
	}
	rc, err := cli.ImagePull(ctx, Image, image.PullOptions{})
	if err != nil {
		return err
	}
	defer rc.Close()
	_, err = io.Copy(io.Discard, rc)
	return err
}

// Remove only touches containers this package created.
func Remove(ctx context.Context, cli *client.Client, name string) error {
	info, err := cli.ContainerInspect(ctx, prefix+name)
	if errdefs.IsNotFound(err) {
		return fmt.Errorf("no html site named %q", name)
	}
	if err != nil {
		return err
	}
	if info.Config.Labels[label] != "true" {
		return fmt.Errorf("%s was not created by sir html, refusing to remove", info.Name)
	}
	return cli.ContainerRemove(ctx, info.ID, container.RemoveOptions{Force: true})
}

func List(ctx context.Context, cli *client.Client, w io.Writer) error {
	cs, err := cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filters.NewArgs(filters.Arg("label", label+"=true")),
	})
	if err != nil {
		return err
	}
	t := table.NewWriter()
	t.SetOutputMirror(w)
	t.AppendHeader(table.Row{"Name", "URL", "Path", "Status"})
	for _, c := range cs {
		t.AppendRow(table.Row{
			strings.TrimPrefix(strings.TrimPrefix(c.Names[0], "/"), prefix),
			"https://" + c.Labels["proxy.host"],
			c.Labels[label+".path"],
			c.Status,
		})
	}
	t.SetStyle(table.StyleRounded)
	t.Render()
	return nil
}

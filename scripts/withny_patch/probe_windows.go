//go:build windows && !cgo

// Portable Windows adapter: reuse the application's external ffprobe instead
// of linking libavformat into the native recorder.
package probe

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

type Options struct{}
type Option func(*Options)

func WithQuiet() Option { return func(*Options) {} }

type result struct {
	Streams []struct {
		Type string `json:"codec_type"`
	} `json:"streams"`
	Format struct {
		Name string `json:"format_name"`
	} `json:"format"`
}

func inspect(input string) (result, error) {
	var data result
	executable, _ := os.Executable()
	program := ""
	for _, candidate := range []string{filepath.Join(filepath.Dir(executable), "..", "ffprobe.exe"), filepath.Join(filepath.Dir(executable), "ffprobe.exe")} {
		if stat, e := os.Stat(candidate); e == nil && !stat.IsDir() {
			program = candidate
			break
		}
	}
	if program == "" {
		program = "ffprobe.exe"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, program, "-v", "error", "-show_entries", "stream=codec_type:format=format_name", "-of", "json", input)
	command.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	command.WaitDelay = time.Second * 2
	var output bytes.Buffer
	command.Stdout = &output
	if err := command.Run(); err != nil {
		return data, errors.New("external ffprobe failed")
	}
	if output.Len() > 1024*1024 {
		return data, errors.New("ffprobe response too large")
	}
	if json.Unmarshal(output.Bytes(), &data) != nil {
		return data, errors.New("invalid ffprobe output")
	}
	return data, nil
}
func Do(inputs []string, opts ...Option) error {
	for _, input := range inputs {
		if _, err := inspect(input); err != nil {
			return err
		}
	}
	return nil
}
func ContainsVideoOrAudio(input string) (bool, error) {
	data, err := inspect(input)
	if err != nil {
		return false, err
	}
	for _, stream := range data.Streams {
		if stream.Type == "video" || stream.Type == "audio" {
			return true, nil
		}
	}
	return false, nil
}
func IsMPEGTSOrAAC(input string) (bool, error) {
	data, err := inspect(input)
	if err != nil {
		return false, err
	}
	for _, name := range strings.Split(data.Format.Name, ",") {
		if name == "mpegts" || name == "aac" {
			return true, nil
		}
	}
	return false, nil
}

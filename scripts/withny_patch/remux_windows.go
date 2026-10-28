package concat

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
)

// Keep muxing external, using the same FFmpeg dependency as the application.
// Multi-file reconciliation is owned by the application's integrity checker.
func Do(ctx context.Context, output string, inputs []string, opts ...Option) error {
	if len(inputs) != 1 {
		return errors.New("managed Withny remux requires one source")
	}
	options := applyOptions(opts)
	executable, _ := os.Executable()
	program := ""
	for _, candidate := range []string{filepath.Join(filepath.Dir(executable), "..", "ffmpeg.exe"), filepath.Join(filepath.Dir(executable), "ffmpeg.exe")} {
		if stat, e := os.Stat(candidate); e == nil && !stat.IsDir() {
			program = candidate
			break
		}
	}
	if program == "" {
		program = "ffmpeg.exe"
	}
	// Inputs are retained by the managed engine even if cancellation interrupts
	// remuxing. No subprocess receives credentials or signed media addresses.
	ctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 2*time.Minute)
	defer cancel()
	args := []string{"-v", "error", "-nostdin", "-y", "-i", inputs[0]}
	if options.audioOnly == 1 {
		args = append(args, "-vn", "-map", "0:a:0")
	} else {
		args = append(args, "-map", "0:v?", "-map", "0:a?")
	}
	args = append(args, "-c", "copy", output)
	command := exec.CommandContext(ctx, program, args...)
	command.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	command.WaitDelay = 2 * time.Second
	if err := command.Run(); err != nil {
		return errors.New("external FFmpeg remux failed")
	}
	return nil
}

package withny

import (
	"context"
	"encoding/json"
	"github.com/Darkness4/withny-dl/withny/api"
	"github.com/rs/zerolog/log"
	"os"
	"time"
)

type Chat struct {
	ChannelID      string
	PassCode       string
	OutputFileName string
}

// Keep a single native subscription and output across reconnects. All writers
// finish before returning, so cancellation cannot close a live channel.
func DownloadChat(ctx context.Context, scraper api.Scraper, chat Chat) error {
	file, err := os.Create(chat.OutputFileName)
	if err != nil {
		return err
	}
	defer file.Close()
	if _, err = file.WriteString("[\n"); err != nil {
		return err
	}
	defer file.WriteString("]\n")
	comments := make(chan *api.Comment, commentBufMax)
	done := make(chan struct{})
	writerCtx, stop := context.WithCancel(ctx)
	defer stop()
	go func() {
		defer close(done)
		for comment := range comments {
			data, e := json.Marshal(comment)
			if e == nil {
				_, e = file.Write(append(data, ',', '\n'))
			}
			if e != nil {
				stop()
				return
			}
		}
	}()
	defer func() { close(comments); <-done }()
	delay := time.Second * 2
	for writerCtx.Err() == nil {
		suuid, e := scraper.FetchStreamUUID(writerCtx, chat.ChannelID, chat.PassCode)
		ws := api.NewCommentWebSocket(scraper.Client)
		if e == nil {
			e = ws.Prepare(writerCtx, chat.ChannelID, chat.PassCode)
		}
		if e == nil {
			conn, dialErr := ws.Dial(writerCtx)
			e = dialErr
			if e == nil {
				e = ws.WatchComments(writerCtx, conn, suuid, comments)
				conn.CloseNow()
			}
		}
		if writerCtx.Err() != nil {
			break
		}
		// Suppress raw errors: network libraries may include signed URLs/tokens.
		log.Warn().Msg("chat connection interrupted; retrying native subscription")
		select {
		case <-writerCtx.Done():
		case <-time.After(delay):
		}
		if delay < 30*time.Second {
			delay *= 2
			if delay > 30*time.Second {
				delay = 30 * time.Second
			}
		}
	}
	return writerCtx.Err()
}

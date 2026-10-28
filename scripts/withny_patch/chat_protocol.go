// Local adaptation of Withny's public Next.js chat authentication flow.
// Kept outside the application executable; upstream withny-dl remains MIT.
package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"
)

var scriptPattern = regexp.MustCompile(`<script[^>]+src="([^"<>]+)"`)
var endpointPattern = regexp.MustCompile(`https://[a-z0-9]+\.appsync-api\.[a-z0-9-]+\.amazonaws\.com/graphql`)
var actionPattern = regexp.MustCompile(`createServerReference\)\("([a-f0-9]+)"[^;]{0,300}"createChatTokenAction"`)
var chatJWT = regexp.MustCompile(`eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`)

func (w *CommentWebSocket) chatRequest(ctx context.Context, method, address string, body io.Reader) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, method, address, body)
	if err != nil {
		return nil, errors.New("invalid chat request")
	}
	creds, err := w.credentialsCache.Get()
	if err != nil {
		return nil, errors.New("chat credentials unavailable")
	}
	req.AddCookie(&http.Cookie{Name: "__Secure-next-auth.session-token", Value: creds.SessionToken})
	req.Header.Set("Origin", "https://www.withny.fun")
	req.Header.Set("User-Agent", w.userAgent)
	if method == "POST" {
		req.Header.Set("Next-Action", w.chatAction)
		req.Header.Set("Content-Type", "text/plain;charset=UTF-8")
		req.Header.Set("Accept", "text/x-component")
	}
	resp, err := w.Client.Client.Do(req)
	if err != nil {
		return nil, errors.New("chat HTTP connection failed")
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, errors.New("chat HTTP request rejected")
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 2*1024*1024+1))
	if err != nil || len(data) > 2*1024*1024 {
		return nil, errors.New("invalid chat HTTP response")
	}
	return data, nil
}

// Prepare discovers deployment-specific endpoint/action from official assets.
// No comments are posted: the action only creates the read subscription token.
func (w *CommentWebSocket) Prepare(parent context.Context, channel, passcode string) error {
	ctx, cancel := context.WithTimeout(parent, 45*time.Second)
	defer cancel()
	pageURL := "https://www.withny.fun/channels/" + url.PathEscape(channel)
	if passcode != "" {
		pageURL += "?passCode=" + url.QueryEscape(passcode)
	}
	page, err := w.chatRequest(ctx, "GET", pageURL, nil)
	if err != nil {
		return err
	}
	scripts := scriptPattern.FindAllSubmatch(page, 64)
	var endpoint, action string
	var mu sync.Mutex
	var workers sync.WaitGroup
	queue := make(chan string, len(scripts))
	for _, m := range scripts {
		u, err := url.Parse(string(m[1]))
		if err != nil {
			continue
		}
		base, _ := url.Parse("https://www.withny.fun")
		u = base.ResolveReference(u)
		if u.Scheme == "https" && u.Host == "www.withny.fun" && strings.HasPrefix(u.Path, "/_next/static/") {
			queue <- u.String()
		}
	}
	close(queue)
	for i := 0; i < 4; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for address := range queue {
				mu.Lock()
				done := endpoint != "" && action != ""
				mu.Unlock()
				if done {
					return
				}
				data, e := w.chatRequest(ctx, "GET", address, nil)
				if e != nil {
					continue
				}
				ep, ac := endpointPattern.Find(data), actionPattern.FindSubmatch(data)
				mu.Lock()
				if len(ep) > 0 {
					endpoint = string(ep)
				}
				if len(ac) > 1 {
					action = string(ac[1])
				}
				mu.Unlock()
			}
		}()
	}
	workers.Wait()
	if endpoint == "" || action == "" {
		return errors.New("official chat protocol could not be discovered")
	}
	streams, err := w.GetStreams(ctx, channel, passcode)
	if err != nil {
		return errors.New("chat stream metadata unavailable")
	}
	streamID := ""
	for _, stream := range streams {
		if stream.ClosedAt == nil {
			streamID = stream.UUID
			break
		}
	}
	if streamID == "" {
		return errors.New("no active chat stream")
	}
	w.chatAction = action
	args := map[string]string{"streamUuid": streamID}
	body, _ := json.Marshal([]any{args})
	data, err := w.chatRequest(ctx, "POST", pageURL, strings.NewReader(string(body)))
	if err != nil {
		return err
	}
	token := chatJWT.Find(data)
	if len(token) == 0 {
		return errors.New("chat token unavailable for current account")
	}
	w.chatToken = string(token)
	w.url, _ = url.Parse(endpoint)
	w.realtimeURL, _ = url.Parse(strings.Replace(endpoint, "appsync-api", "appsync-realtime-api", 1))
	w.realtimeURL.Scheme = "wss"
	return nil
}

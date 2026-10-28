package withny

import (
	"encoding/json"
	"fmt"
)

func reportNativeState(kind, channel, stream string) {
	data, _ := json.Marshal(map[string]string{"kind": kind, "channel": channel, "stream": stream})
	fmt.Printf("LIVE_NATIVE_STATE:%s\n", data)
}

func reportNativePoll(channel string, online bool, err error) {
	state := "idle"
	if err != nil {
		state = "error"
	} else if online {
		state = "online"
	}
	reportNativeState(state, channel, "")
}

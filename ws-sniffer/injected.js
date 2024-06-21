const forwardingPort = 8421;
console.log("[ws-sniffer] websocket sniffer started, forwarding to local ws port " + forwardingPort);

wsHook.before = function(data, url, wsObject) {
    console.log("[ws-sniffer] sending message to " + url + ", data: " + data);
    forwardMsg("send", url, data);
}

// Make sure your program calls `wsClient.onmessage` event handler somewhere.
wsHook.after = function(messageEvent, url, wsObject) {
    console.log("[ws-sniffer] received message from " + url + ", data: " + messageEvent.data);
    forwardMsg("recv", url, messageEvent.data);
    return messageEvent;
}

function forwardMsg(action, url, data) {
    var ws = new RealWebSocket("ws://localhost:" + forwardingPort);
    ws.onopen = function() {
        var b64 = toBase64(data)
        ws.send(JSON.stringify({action: action, url: url, data: b64}));
        ws.close();
    };
}

function toBase64(input) {
    if (typeof input === 'string') {
        return btoa(input);
    } else if (input instanceof ArrayBuffer) {
        let binary = '';
        const bytes = new Uint8Array(input);
        const len = bytes.byteLength;
        for (let i = 0; i < len; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    } else {
        return '';
    }
}

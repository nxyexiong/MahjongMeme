var el = document.createElement("script");
el.src = chrome.runtime.getURL("wsHook.js");
document.documentElement.appendChild(el);

el.onload = function() {
    var el = document.createElement("script");
    el.src = chrome.runtime.getURL("injected.js");
    document.documentElement.appendChild(el);

    console.log("[ws-sniffer] injected");
};

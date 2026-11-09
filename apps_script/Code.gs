// "Sync now" for the spreadsheet: adds a Sync menu that starts the QBO sync right away,
// instead of waiting for the daily run. Paste into the sheet's Apps Script project
// (Extensions > Apps Script), along with appsscript.json.
//
// The request carries a Google identity token for whoever clicked. The function checks
// Google's signature on it, that it was issued to this script, and that the account is
// allowed, so no password or key is stored here. The function's URL goes in the SYNC_URL
// script property (Project Settings > Script properties).

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Sync")
    .addItem("Sync now", "syncNow")
    .addToUi();
}

function syncNow() {
  const url = PropertiesService.getScriptProperties().getProperty("SYNC_URL");
  if (!url) {
    throw new Error("Set the SYNC_URL script property to the stack's SyncUrl output");
  }

  const token = ScriptApp.getIdentityToken();
  if (!token) {
    throw new Error("No identity token: check that appsscript.json lists the openid scope");
  }

  const response = UrlFetchApp.fetch(url, {
    method: "post",
    headers: { Authorization: "Bearer " + token },
    muteHttpExceptions: true,
  });

  const code = response.getResponseCode();
  // the function runs one sync at a time; AWS answers 429 while one is running
  const message = code === 202 ? "The sheet updates in a few seconds. Check the Sync Status tab for the result."
                : code === 429 ? "A sync is already running. Try again in a few seconds."
                : response.getContentText() + " (HTTP " + code + ")";
  SpreadsheetApp.getActive().toast(message, code === 202 ? "Sync started" : "Sync not started", 10);
}

// setup helper: logs this script's OAuth client ID (the "aud" of its identity tokens),
// which the stack needs as GoogleScriptClientId. Logs the claim only, never the token
function logClientId() {
  const token = ScriptApp.getIdentityToken();
  if (!token) {
    throw new Error("No identity token: check that appsscript.json lists the openid scope");
  }

  // a token is three base64url parts joined by dots; the middle one holds the claims.
  // JWTs drop the "=" padding, which the decoder needs
  let payload = token.split(".")[1];
  payload += "=".repeat((4 - payload.length % 4) % 4);
  const claims = JSON.parse(Utilities.newBlob(Utilities.base64DecodeWebSafe(payload)).getDataAsString());

  Logger.log("Client ID (aud): " + claims.aud);
  Logger.log("Email in token: " + (claims.email || "none, add the userinfo.email scope"));
}

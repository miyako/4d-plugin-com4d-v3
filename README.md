# 4d-plugin-com4d-v3
 
 COM4D is a simple inter-process communication tool for 4D on Windows, built on top of Windows COM Automation. One 4D process serializes a collection of values with `COM Write`, which hands them to the plugin's own in-process COM server (registered under the ProgID `COM4Dv3.Server`); that server stores them as JSON in a fixed-size, named shared-memory buffer. Any other process on the same Windows user session — a different running instance of 4D, or a different application entirely — can then call `COM Read` to retrieve and decode everything that's been written since the last read. All three exposed commands (`COM Setup`, `COM Write`, `COM Read`) return an `Object`.
 
 ## Summary
 
 | Command | Returns | Purpose |
 |---|---|---|
 | [COM Setup](#com-setup) | Object | Register, unregister, or report the Windows COM registration status of the plugin's internal server. |
 | [COM Write](#com-write) | Object | Serialize a collection of values and hand them to the internal COM server for storage. |
 | [COM Read](#com-read) | Object | Retrieve and clear everything written via `COM Write` since the last `COM Read`. |
 
 **Platforms:** Windows only.
 
 ---
 
 ## Requirements & platform notes
 
 - **macOS is a no-op.** The plugin has no macOS implementation — `COM Setup`, `COM Write`, and `COM Read` all just return an empty `Object` on macOS. There is no partial parity to rely on; treat this plugin as Windows-only.
 - **You must register before writing.** `COM Write` looks up the internal COM server by ProgID at call time; if it hasn't been registered (via `COM Setup` in register mode), `COM Write` returns `{success: false}` with no further detail. There's no automatic self-registration.
 - **Registration is fire-and-forget, not synchronous.** `COM Setup` in register/unregister mode launches `REGSVR32.EXE` silently via `ShellExecuteEx` and does **not** wait for it to finish before returning. Don't assume the registration has actually completed the instant `COM Setup` returns — if you need to be sure, poll `COM Setup` in status mode until `isRegistered` reflects the change.
 - **Registration is per-user, not machine-wide.** It's installed with regsvr32's `/i:user` switch, so no administrator rights are required, but it only takes effect for the current Windows user.
 - **The exchange buffer is shared and unscoped.** The shared memory segment is created under one fixed name for the whole Windows session — it is not scoped per 4D database, per connection, or per application. Any process running as the same Windows user and using this plugin shares the same mailbox.
 - **No built-in locking.** The exchange buffer has no internal mutex or semaphore protecting concurrent access. If multiple processes call `COM Write` at (almost) the same moment, or a `COM Write` races a `COM Read`, an update can occasionally be lost. Avoid firing many concurrent `COM Write`/`COM Read` calls without any pacing.
 - **The buffer is capped at 16 MB.** If you call `COM Write` repeatedly without an intervening `COM Read`, the accumulated JSON can eventually exceed the internal buffer; once it does, further `COM Write` calls fail (`success: false`) until a `COM Read` drains it.
 - **Only a subset of 4D value types survive `COM Write`.** Text, Boolean, Date, Time, Longint/Integer, Real, and `Null` are supported. Any other element in the collection (an `Object`, a `Collection`, a `Picture`, a `Blob`, and so on) is silently converted to an empty value rather than raising an error — see [Error handling](#error-handling--troubleshooting).
 
 ---
 
 ## COM Setup
 
 ### Syntax
 
 ```
 COM Setup ( mode ) -> Object
 ```
 
 | Parameter | Type | Description |
 |---|---|---|
 | `mode` | Longint | One of the plugin's setup constants. `com register` registers the internal COM server; `com unregister` unregisters it; `com get status` (or any other value) just reports the current registration status. |
 | Result | Object | See Description below — the fields present depend on `mode`. |
 
 The exact constant names are defined in the plugin's own constant list; the two confirmed from the plugin's test file are `com register` and `com get status` (see Example). If `com unregister`'s exact spelling isn't available via autocomplete in your project, you can pass the raw Longint value `1` instead — the plugin's dispatch is a plain numeric switch (`0` = register, `1` = unregister, anything else = status).
 
 ### Description
 
 - In **register** or **unregister** mode, the result object always has `clsid` (Text) and `progid` (Text) — the plugin's fixed CLSID string and ProgID (`COM4Dv3.Server`). If the underlying `REGSVR32.EXE` launch fails to even start, the object additionally gets `code` (Longint, the Windows error code) and `errorMessage` (Text, the formatted system message) — but a successful *launch* doesn't guarantee the registration itself succeeded (see the async caveat above).
 - In **status** mode, the result object has `clsid`, `progid`, and `isRegistered` (Boolean) — whether the ProgID currently resolves to a class ID via `CLSIDFromProgID`. Status mode never populates `code`/`errorMessage`, even if the plugin isn't registered; `isRegistered: false` is the only signal.
 - Register/unregister mode results never include `isRegistered`; status mode results never include `code`/`errorMessage`. Don't check for a field the mode doesn't produce.
 
 ### Example
 
 From the plugin's own test method (`TEST.4dm`):
 
 ```4d
 $status:=COM Setup (com get status)
 
 If (Not:C34($status.isRegistered))
     $status:=COM Setup (com register)
 End if 
 ```
 
 Unregistering and checking the outcome:
 
 ```4d
 $status:=COM Setup (com unregister)
 If ($status.code#0)
     ALERT:C41("Unregister may have failed: "+$status.errorMessage)
 End if 
 ```
 
 ---
 
 ## COM Write
 
 ### Syntax
 
 ```
 COM Write ( values ) -> Object
 ```
 
 | Parameter | Type | Description |
 |---|---|---|
 | `values` | Collection | Ordered collection of values to send. Supported element types: Text, Boolean, Date, Time, Longint/Integer, Real, `Null`. Any other element type is sent as an empty value (see Requirements above). |
 | Result | Object | `success` (Boolean); `data` (Text) present only when `success` is `true`. |
 
 ### Description
 
 Each call creates a fresh in-process instance of the internal COM server, hands it the collection (converted element-by-element to COM `VARIANT`s, in the original collection order), and immediately releases it — there's no persistent connection between calls. `data`, when present, is the JSON-encoded echo of exactly what was recorded (useful to confirm what was sent, not an external computation result).
 
 If the server isn't registered, if COM initialization fails, or if the internal buffer is full (see Requirements), the result is just `{success: false}` — there's no `code`/`errorMessage` field on this command, unlike `COM Setup`.
 
 ### Example
 
 From the plugin's own test method (`TEST.4dm`):
 
 ```4d
 C_COLLECTION:C1488($params)
 $params:=New collection:C1472("Hello!";Current date:C33;Pi:K30:1;True:C214;Null:C1517;Current time:C178;MAXLONG:K35:2)
 
 $status:=COM Write ($params)
 If ($status.success)
     $status:=COM Read 
 End if 
 ```
 
 Sending a smaller, purely-text payload and checking the result:
 
 ```4d
 $payload:=New collection:C1472("ping";1;True:C214)
 $status:=COM Write ($payload)
 If (Not:C34($status.success))
     ALERT:C41("COM Write failed — is the plugin registered?")
 End if 
 ```
 
 ---
 
 ## COM Read
 
 ### Syntax
 
 ```
 COM Read -> Object
 ```
 
 No parameters.
 
 | Parameter | Type | Description |
 |---|---|---|
 | Result | Object | `success` (Boolean); `values` (Collection) present only when `success` is `true`. |
 
 ### Description
 
 `COM Read` is **destructive**: it retrieves everything accumulated in the shared buffer since the last successful read and clears the buffer in the same call. Calling it a second time immediately afterward, with no intervening `COM Write`, returns `success: false` — there's nothing left to read.
 
 `values` is a collection with one element per `COM Write` call recorded since the last read; each of those elements is itself a collection, one entry per parameter that was passed to that `COM Write`. Each decoded parameter is an `Object` with a single key — the original COM `VARIANT` type tag (for example `VT_BSTR`, `VT_BOOL`, `VT_I4`, `VT_R8`, `VT_EMPTY`, `VT_NULL`) — whose value is the corresponding 4D value. A parameter that wasn't decodable comes back as `Null` instead of a typed object. Since the key name varies per parameter, you'll generally need to inspect the object's key(s) at runtime (4D has commands for listing an object's property names — check your Language Reference for the exact command and tag number for your 4D version) rather than assuming a fixed key.
 
 ### Example
 
 From the plugin's own test method (`TEST_read.4dm`):
 
 ```4d
 $status:=COM Read 
 ```
 
 A fuller pattern, iterating the decoded values:
 
 ```4d
 $status:=COM Read 
 If ($status.success)
     For each ($call;$status.values)
         For each ($param;$call)
             ALERT:C41(String:C10($param))  //inspect the raw decoded parameter object
         End for each 
     End for each 
 End if 
 ```
 
 ---
 
 ## Full worked example — writing from one process, reading from another
 
 This is the plugin's actual purpose: the value crosses a process boundary. The two sample methods shipped with the plugin demonstrate exactly that split — run `TEST.4dm` from one 4D application (or instance) to set up and write, and run `TEST_read.4dm` from a separate one to pick the data up.
 
 **Writer side**, from `TEST.4dm`:
 
 ```4d
 $status:=COM Setup (com get status)
 
 If (Not:C34($status.isRegistered))
     $status:=COM Setup (com register)
 End if 
 
 C_COLLECTION:C1488($params)
 $params:=New collection:C1472("Hello!";Current date:C33;Pi:K30:1;True:C214;Null:C1517;Current time:C178;MAXLONG:K35:2)
 
 $status:=COM Write ($params)
 If ($status.success)
     $status:=COM Read 
 End if 
 ```
 
 **Reader side**, from `TEST_read.4dm`:
 
 ```4d
 $status:=COM Read 
 ```
 
 Run the writer method first; then, from the *other* process, run the reader method to pick up whatever the writer hasn't already consumed via its own `COM Read` call.
 
 ---
 
 ## Error handling & troubleshooting
 
 - **`COM Write` fails silently if the server isn't registered.** You only get `{success: false}` — no error code or message. Confirm `COM Setup (com get status)` reports `isRegistered: true` first if writes are unexpectedly failing.
 - **Registration doesn't finish before `COM Setup` returns.** The register/unregister call only launches `regsvr32.exe`; it doesn't wait. If you register and immediately write, there's a race where the server isn't actually ready yet. Poll status if you need certainty.
 - **Unsupported collection element types don't raise an error.** An `Object`, `Collection`, `Picture`, or `Blob` passed inside the `values` collection to `COM Write` is silently converted to an empty value rather than failing the call — check your own data shape before writing if this matters.
 - **The buffer is shared across every process on the same Windows user session.** It isn't scoped to a database, project, or connection — a second, unrelated 4D application using this plugin at the same time shares the same exchange buffer.
 - **`COM Read` is consume-once.** A second `COM Read` right after a successful one returns `success: false` — there's no "peek" without clearing.
 - **A full buffer fails quietly, too.** If `COM Write` is called many times without a `COM Read` draining it, once the internal 16 MB buffer would be exceeded, further `COM Write` calls return `success: false` until something reads.
 - **This is Windows-only.** Calling any of the three commands on macOS returns an empty `Object` with none of the fields described above — there's no error, just nothing useful in the result.
 
 ---
 
 ## Quick reference
 
 ```4d
 // one-time setup
 $status:=COM Setup (com get status)
 If (Not:C34($status.isRegistered))
     $status:=COM Setup (com register)
 End if 
 
 // write
 C_COLLECTION:C1488($params)
 $params:=New collection:C1472("value1";42;True:C214)
 $status:=COM Write ($params)
 
 // read (from this or another process)
 $status:=COM Read 
 If ($status.success)
     // $status.values holds one collection per COM Write call since the last read
 End if 
 ```

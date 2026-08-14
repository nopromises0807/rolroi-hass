ROL-ROI Steel Door 2.1.0
This version corrects the Cloud authentication to match the original APK:

POST /v3/user/login is multipart/form-data, not JSON.
APK signature is included in every POST.
Device-list GET includes the same signature.
Door control uses MQTT WebSocket ws://<mqtt-server>:8080/ws.
Door commands are AES-CBC encrypted using the APK keyById()/ivById() algorithm.
Cloud device hierarchy is flattened from house -> rooms -> devices.
Install as /config/custom_components/rol_roi_steel_door/ and remove the older copy first.

v2.1.2 control fix
The door command payload now matches the APK: { "sdr": <1..5>, "u": <user_id>, "src": 1 }, and all APK door root types sdoor1..sdoor5 are accepted. MQTT publish remains binary AES-CBC ciphertext to the device topicsub.

v2.1.4
Sync pcnslot (ô thoáng) from MQTT.

Keep the cover open/closable when main shutter is at 0% but the cleft is still open.

Add a dedicated Ô thoáng percentage sensor.

v2.1.5: use effective cover position = max(main door %, cleft %) so HA does not show the shutter as closed while the advanced opening is still active.

v2.1.6: keep OPEN/CLOSE actions available at all reported positions.

v2.1.7: display main door % and vent/cleft % directly in the cover control entity name.

v2.1.8: fixed cover.py syntax and replaces the standard state text with 'Cửa X% | Ô thoáng Y%'.

v2.1.9: remove HA's automatic trailing ' · NN%' from the custom cover state display.

v2.2.3
hiện % cửa, ô thoáng

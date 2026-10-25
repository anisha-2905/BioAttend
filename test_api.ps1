#matches actual API key
$API_KEY = "7e0386ccf60481dbef2ef5ba945e490705f0903b41256f8a6fcc1f63441ab34a"

Write-Host "---- Test 1: Ping ----"
Invoke-WebRequest -Uri "http://127.0.0.1:5000/api/ping" `
  -Method GET -Headers @{ "X-API-Key" = $API_KEY } | Select-Object -Expand Content

Write-Host "`n---- Test 2: Valid Present ----"
Invoke-WebRequest -Uri "http://127.0.0.1:5000/api/mark_attendance" `
  -Method POST -Headers @{ "X-API-Key" = $API_KEY } `
  -ContentType "application/json" `
  -Body '{ "student_id": 1, "status": "present", "scanned_at": "2025-09-04T09:30:00Z" }' `
  | Select-Object -Expand Content

Write-Host "`n---- Test 3: Valid Absent ----"
Invoke-WebRequest -Uri "http://127.0.0.1:5000/api/mark_attendance" `
  -Method POST -Headers @{ "X-API-Key" = $API_KEY } `
  -ContentType "application/json" `
  -Body '{ "student_id": 1, "status": "absent", "scanned_at": "2025-09-04T09:35:00Z" }' `
  | Select-Object -Expand Content

Write-Host "`n---- Test 4: Missing student_id ----"
Invoke-WebRequest -Uri "http://127.0.0.1:5000/api/mark_attendance" `
  -Method POST -Headers @{ "X-API-Key" = $API_KEY } `
  -ContentType "application/json" `
  -Body '{ "status": "present" }' `
  | Select-Object -Expand Content

Write-Host "`n---- Test 5: Invalid status ----"
Invoke-WebRequest -Uri "http://127.0.0.1:5000/api/mark_attendance" `
  -Method POST -Headers @{ "X-API-Key" = $API_KEY } `
  -ContentType "application/json" `
  -Body '{ "student_id": 1, "status": "late" }' `
  | Select-Object -Expand Content

Write-Host "`n---- Test 6: Wrong API key ----"
Invoke-WebRequest -Uri "http://127.0.0.1:5000/api/mark_attendance" `
  -Method POST -Headers @{ "X-API-Key" = "wrongtoken" } `
  -ContentType "application/json" `
  -Body '{ "student_id": 1, "status": "present" }' `
  | Select-Object -Expand Content

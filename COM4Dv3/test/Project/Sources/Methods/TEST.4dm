//%attributes = {}
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
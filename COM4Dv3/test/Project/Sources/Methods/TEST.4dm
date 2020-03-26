//%attributes = {}
$status:=COM Read 

$status:=COM Setup (com get status)

If (Not:C34($status.isRegistered))
	$status:=COM Setup (com register)
End if 

C_COLLECTION:C1488($params)
$params:=New collection:C1472("Hello!";"World?")

$status:=COM Write ($params)
If ($status.success)
	$status:=COM Read 
End if 
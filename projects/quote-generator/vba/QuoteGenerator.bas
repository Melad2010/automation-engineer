Attribute VB_Name = "QuoteGenerator"
'==============================================================================
' QuoteGenerator - the same pricing rules as quotekit/pricing.py, in VBA.
'
' Use this when the client wants a macro-driven workbook (.xlsm) instead of the
' formula-driven one that build_tool.py produces. The rules are identical:
'
'   unit list  = product list price + the price of each selected option
'   discount   = quantity break + customer tier + manual discount
'   margin cap = the discount stops at the margin floor, and says so
'   net price  = ROUND(unit list * (1 - discount), 2)
'   line total = ROUND(net price * quantity, 2)
'   VAT        = applied once to the subtotal, not per line
'
' Sheets it expects (the layout build_tool.py writes):
'   Catalog  A:E  Code | Name | List price | Cost | Lead time
'            G:L  Key  | Product | Option | Option name | Price | Cost
'   Rules    A3:B* quantity breaks, D3:E* tiers, H2 VAT, H3 floor, H4 validity
'   Quote    B4 tier, rows 9..20: B product, D:F options, G qty
'
' Install: Alt+F11 -> File -> Import File -> QuoteGenerator.bas
'==============================================================================
Option Explicit

Private Const QUOTE_SHEET As String = "Quote"
Private Const CATALOG_SHEET As String = "Catalog"
Private Const RULES_SHEET As String = "Rules"
Private Const FIRST_LINE As Long = 9
Private Const MAX_LINES As Long = 12
Private Const SHEET_PASSWORD As String = "quote"

' Filled by PriceLine so the caller can report a capped discount.
Public LastLineWasCapped As Boolean
Public LastLineNote As String


'--- Public entry points ------------------------------------------------------

' Prices every filled row on the Quote sheet and writes the results back.
Public Sub BuildQuote()
    Dim quoteSheet As Worksheet
    Dim row As Long
    Dim tier As String
    Dim subtotal As Double, vatAmount As Double
    Dim notes As String
    Dim unitList As Double, unitCost As Double
    Dim discount As Double, netPrice As Double, lineTotal As Double
    Dim quantity As Long

    Set quoteSheet = ThisWorkbook.Worksheets(QUOTE_SHEET)
    tier = Trim$(CStr(quoteSheet.Range("B4").Value))

    If Not TierExists(tier) Then
        MsgBox "Customer tier '" & tier & "' is not in the Rules sheet.", vbExclamation
        Exit Sub
    End If

    Unprotect quoteSheet
    subtotal = 0

    For row = FIRST_LINE To FIRST_LINE + MAX_LINES - 1
        If Len(Trim$(CStr(quoteSheet.Cells(row, "B").Value))) = 0 Then
            quoteSheet.Range(quoteSheet.Cells(row, "C"), quoteSheet.Cells(row, "K")).ClearContents
        Else
            quantity = QuantityOf(quoteSheet, row)
            If quantity < 1 Then
                MsgBox "Row " & row & ": quantity must be a whole number of 1 or more.", vbExclamation
                Protect quoteSheet
                Exit Sub
            End If

            unitList = UnitPrice(quoteSheet, row, False)
            unitCost = UnitPrice(quoteSheet, row, True)
            discount = PriceLine(unitList, unitCost, quantity, tier, ManualDiscount(quoteSheet, row))
            netPrice = RoundHalfUp(unitList * (1 - discount), 2)
            lineTotal = RoundHalfUp(netPrice * quantity, 2)

            quoteSheet.Cells(row, "C").Value = ProductName(quoteSheet.Cells(row, "B").Value)
            quoteSheet.Cells(row, "H").Value = unitList
            quoteSheet.Cells(row, "I").Value = discount
            quoteSheet.Cells(row, "J").Value = netPrice
            quoteSheet.Cells(row, "K").Value = lineTotal
            quoteSheet.Cells(row, "M").Value = unitCost * quantity

            If LastLineWasCapped Then notes = notes & "Row " & row & ": " & LastLineNote & vbLf
            subtotal = subtotal + lineTotal
        End If
    Next row

    subtotal = RoundHalfUp(subtotal, 2)
    vatAmount = RoundHalfUp(subtotal * SettingValue("H2"), 2)

    quoteSheet.Cells(FIRST_LINE + MAX_LINES + 1, "K").Value = subtotal
    quoteSheet.Cells(FIRST_LINE + MAX_LINES + 2, "K").Value = vatAmount
    quoteSheet.Cells(FIRST_LINE + MAX_LINES + 3, "K").Value = RoundHalfUp(subtotal + vatAmount, 2)
    quoteSheet.Range("B6").Value = quoteSheet.Range("B5").Value + SettingValue("H4")

    Protect quoteSheet

    If Len(notes) > 0 Then
        MsgBox "Quote built. Some lines hit the margin floor:" & vbLf & vbLf & notes, vbInformation
    End If
End Sub


' Saves the customer-facing part of the Quote sheet as a PDF next to the workbook.
Public Sub ExportQuotePdf()
    Dim quoteSheet As Worksheet
    Dim target As String

    Set quoteSheet = ThisWorkbook.Worksheets(QUOTE_SHEET)
    If Len(ThisWorkbook.Path) = 0 Then
        MsgBox "Save the workbook first, so the PDF has somewhere to go.", vbExclamation
        Exit Sub
    End If

    target = ThisWorkbook.Path & Application.PathSeparator & _
             "Quote_" & CleanFileName(CStr(quoteSheet.Range("B3").Value)) & "_" & _
             Format$(Date, "yyyymmdd") & ".pdf"

    On Error GoTo ExportFailed
    quoteSheet.ExportAsFixedFormat Type:=xlTypePDF, Filename:=target, Quality:=xlQualityStandard
    MsgBox "Saved " & target, vbInformation
    Exit Sub

ExportFailed:
    MsgBox "Could not write the PDF: " & Err.Description, vbCritical
End Sub


'--- The pricing rule ---------------------------------------------------------

' Returns the discount to apply, as a fraction, already capped by the margin
' floor. Sets LastLineWasCapped / LastLineNote as a side effect.
Public Function PriceLine(ByVal unitList As Double, ByVal unitCost As Double, _
                          ByVal quantity As Long, ByVal tier As String, _
                          ByVal manualDiscount As Double) As Double
    Dim requested As Double
    Dim ceiling As Double
    Dim floor As Double

    LastLineWasCapped = False
    LastLineNote = ""

    requested = QuantityDiscount(quantity) + TierDiscount(tier) + manualDiscount

    floor = SettingValue("H3")
    If unitList <= 0 Then
        PriceLine = 0
        Exit Function
    End If

    ' The largest discount that still leaves `floor` margin on the line.
    ceiling = 1 - (unitCost / (1 - floor)) / unitList
    If ceiling < 0 Then ceiling = 0

    If requested > ceiling Then
        ' Full precision on purpose - rounding the cap up breaches the floor.
        PriceLine = ceiling
        LastLineWasCapped = True
        LastLineNote = "discount capped at " & Format$(ceiling, "0.00%") & _
                       " by the " & Format$(floor, "0.0%") & " margin floor" & _
                       " (requested " & Format$(requested, "0.00%") & ")"
    Else
        PriceLine = requested
    End If
End Function


' Excel's ROUND rounds halves away from zero; VBA's Round() rounds to even.
' The quote must match the printed price list, so this does it explicitly.
Public Function RoundHalfUp(ByVal value As Double, ByVal decimals As Long) As Double
    Dim factor As Double
    factor = 10 ^ decimals
    If value >= 0 Then
        RoundHalfUp = Int(value * factor + 0.5 + 0.000000001) / factor
    Else
        RoundHalfUp = -Int(-value * factor + 0.5 + 0.000000001) / factor
    End If
End Function


'--- Lookups ------------------------------------------------------------------

Private Function UnitPrice(ByVal quoteSheet As Worksheet, ByVal row As Long, _
                           ByVal wantCost As Boolean) As Double
    Dim total As Double
    Dim column As Variant
    Dim productCode As String
    Dim optionCode As String

    productCode = Trim$(CStr(quoteSheet.Cells(row, "B").Value))
    total = ProductValue(productCode, IIf(wantCost, 4, 3))

    For Each column In Array("D", "E", "F")
        optionCode = Trim$(CStr(quoteSheet.Cells(row, CStr(column)).Value))
        If Len(optionCode) > 0 Then
            total = total + OptionValue(productCode, optionCode, IIf(wantCost, 12, 11))
        End If
    Next column

    UnitPrice = total
End Function


Private Function ProductValue(ByVal code As String, ByVal columnIndex As Long) As Double
    Dim found As Range
    Set found = ThisWorkbook.Worksheets(CATALOG_SHEET).Columns("A").Find( _
        What:=code, LookAt:=xlWhole, MatchCase:=False)
    If found Is Nothing Then
        Err.Raise vbObjectError + 1, "QuoteGenerator", "Unknown product code: " & code
    End If
    ProductValue = CDbl(ThisWorkbook.Worksheets(CATALOG_SHEET).Cells(found.row, columnIndex).Value)
End Function


Private Function OptionValue(ByVal productCode As String, ByVal optionCode As String, _
                             ByVal columnIndex As Long) As Double
    Dim found As Range
    Set found = ThisWorkbook.Worksheets(CATALOG_SHEET).Columns("G").Find( _
        What:=productCode & "|" & optionCode, LookAt:=xlWhole, MatchCase:=False)
    If found Is Nothing Then
        Err.Raise vbObjectError + 2, "QuoteGenerator", _
                  "Option " & optionCode & " does not belong to " & productCode
    End If
    OptionValue = CDbl(ThisWorkbook.Worksheets(CATALOG_SHEET).Cells(found.row, columnIndex).Value)
End Function


Private Function ProductName(ByVal code As Variant) As String
    On Error Resume Next
    ProductName = CStr(ThisWorkbook.Worksheets(CATALOG_SHEET).Cells( _
        ThisWorkbook.Worksheets(CATALOG_SHEET).Columns("A").Find( _
            What:=CStr(code), LookAt:=xlWhole).row, 2).Value)
End Function


' The highest quantity break the quantity reaches.
Private Function QuantityDiscount(ByVal quantity As Long) As Double
    Dim rules As Worksheet
    Dim row As Long
    Dim discount As Double

    Set rules = ThisWorkbook.Worksheets(RULES_SHEET)
    discount = 0
    row = 3
    Do While Len(CStr(rules.Cells(row, 1).Value)) > 0
        If quantity >= CLng(rules.Cells(row, 1).Value) Then
            discount = CDbl(rules.Cells(row, 2).Value)
        End If
        row = row + 1
    Loop

    QuantityDiscount = discount
End Function


Private Function TierDiscount(ByVal tier As String) As Double
    Dim rules As Worksheet
    Dim row As Long

    Set rules = ThisWorkbook.Worksheets(RULES_SHEET)
    row = 3
    Do While Len(CStr(rules.Cells(row, 4).Value)) > 0
        If StrComp(CStr(rules.Cells(row, 4).Value), tier, vbTextCompare) = 0 Then
            TierDiscount = CDbl(rules.Cells(row, 5).Value)
            Exit Function
        End If
        row = row + 1
    Loop

    Err.Raise vbObjectError + 3, "QuoteGenerator", "Unknown customer tier: " & tier
End Function


Private Function TierExists(ByVal tier As String) As Boolean
    On Error GoTo NotFound
    TierDiscount tier
    TierExists = True
    Exit Function
NotFound:
    TierExists = False
End Function


Private Function SettingValue(ByVal address As String) As Double
    SettingValue = CDbl(ThisWorkbook.Worksheets(RULES_SHEET).Range(address).Value)
End Function


'--- Small helpers ------------------------------------------------------------

Private Function QuantityOf(ByVal quoteSheet As Worksheet, ByVal row As Long) As Long
    Dim raw As Variant
    raw = quoteSheet.Cells(row, "G").Value
    If Not IsNumeric(raw) Then
        QuantityOf = 0
    ElseIf CDbl(raw) <> Int(CDbl(raw)) Then
        QuantityOf = 0
    Else
        QuantityOf = CLng(raw)
    End If
End Function


Private Function ManualDiscount(ByVal quoteSheet As Worksheet, ByVal row As Long) As Double
    Dim raw As Variant
    raw = quoteSheet.Cells(row, "L").Value
    If IsNumeric(raw) And Len(CStr(raw)) > 0 Then
        If CDbl(raw) > 0 Then ManualDiscount = CDbl(raw)
    End If
End Function


Private Function CleanFileName(ByVal name As String) As String
    Dim bad As Variant
    Dim result As String
    result = Trim$(name)
    For Each bad In Array("\", "/", ":", "*", "?", """", "<", ">", "|")
        result = Replace(result, CStr(bad), "-")
    Next bad
    If Len(result) = 0 Then result = "customer"
    CleanFileName = result
End Function


Private Sub Unprotect(ByVal target As Worksheet)
    On Error Resume Next
    target.Unprotect Password:=SHEET_PASSWORD
End Sub


Private Sub Protect(ByVal target As Worksheet)
    On Error Resume Next
    target.Protect Password:=SHEET_PASSWORD, UserInterfaceOnly:=True
End Sub

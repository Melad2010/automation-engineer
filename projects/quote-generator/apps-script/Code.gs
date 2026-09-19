/**
 * Quote generator for Google Sheets — the same pricing rules as
 * quotekit/pricing.py and vba/QuoteGenerator.bas.
 *
 * Install: Extensions -> Apps Script, paste this file, save, reload the sheet.
 * A "Quote" menu appears next to Help.
 *
 * Sheet layout it expects (what build_tool.py writes, imported into Sheets):
 *   Catalog  A:E  Code | Name | List price | Cost | Lead time
 *            G:L  Key  | Product | Option | Option name | Price | Cost
 *   Rules    A3:B* quantity breaks, D3:E* tiers, H2 VAT, H3 floor, H4 validity
 *   Quote    B4 tier, rows 9..20: B product, D:F options, G qty, L manual discount
 */

var QUOTE_SHEET = 'Quote';
var CATALOG_SHEET = 'Catalog';
var RULES_SHEET = 'Rules';
var FIRST_LINE = 9;
var MAX_LINES = 12;

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Quote')
    .addItem('Build quote', 'buildQuote')
    .addItem('Email quote as PDF', 'emailQuotePdf')
    .addToUi();
}

/** Rounds halves away from zero, the way a printed price list reads. */
function roundHalfUp(value, decimals) {
  var factor = Math.pow(10, decimals);
  var shifted = value * factor;
  var epsilon = shifted >= 0 ? 1e-9 : -1e-9;
  return Math.trunc(shifted + (shifted >= 0 ? 0.5 : -0.5) + epsilon) / factor;
}

function loadCatalog(book) {
  var sheet = book.getSheetByName(CATALOG_SHEET);
  var products = {};
  var options = {};

  sheet.getRange(2, 1, Math.max(sheet.getLastRow() - 1, 1), 5).getValues()
    .forEach(function (row) {
      if (row[0]) {
        products[String(row[0]).trim()] = {
          name: row[1], price: Number(row[2]), cost: Number(row[3]), lead: Number(row[4])
        };
      }
    });

  sheet.getRange(2, 7, Math.max(sheet.getLastRow() - 1, 1), 6).getValues()
    .forEach(function (row) {
      if (row[0]) {
        options[String(row[0]).trim()] = { price: Number(row[4]), cost: Number(row[5]) };
      }
    });

  return { products: products, options: options };
}

function loadRules(book) {
  var sheet = book.getSheetByName(RULES_SHEET);
  var breaks = sheet.getRange(3, 1, Math.max(sheet.getLastRow() - 2, 1), 2).getValues()
    .filter(function (row) { return row[0] !== '' && row[0] !== null; })
    .map(function (row) { return { minQuantity: Number(row[0]), discount: Number(row[1]) }; })
    .sort(function (a, b) { return a.minQuantity - b.minQuantity; });

  var tiers = {};
  sheet.getRange(3, 4, Math.max(sheet.getLastRow() - 2, 1), 2).getValues()
    .forEach(function (row) {
      if (row[0]) { tiers[String(row[0]).trim().toLowerCase()] = Number(row[1]); }
    });

  return {
    breaks: breaks,
    tiers: tiers,
    vat: Number(sheet.getRange('H2').getValue()),
    marginFloor: Number(sheet.getRange('H3').getValue()),
    validDays: Number(sheet.getRange('H4').getValue())
  };
}

function quantityDiscount(rules, quantity) {
  var discount = 0;
  rules.breaks.forEach(function (item) {
    if (quantity >= item.minQuantity) { discount = item.discount; }
  });
  return discount;
}

/**
 * The discount to apply, as a fraction, already capped by the margin floor.
 * Returns { discount, capped, requested }.
 */
function priceLine(rules, unitList, unitCost, quantity, tier, manualDiscount) {
  var tierDiscount = rules.tiers[String(tier).trim().toLowerCase()];
  if (tierDiscount === undefined) {
    throw new Error('Unknown customer tier: ' + tier);
  }

  var requested = quantityDiscount(rules, quantity) + tierDiscount + (manualDiscount || 0);
  if (unitList <= 0) { return { discount: 0, capped: false, requested: requested }; }

  // The largest discount that still leaves marginFloor margin on the line.
  var ceiling = Math.max(0, 1 - (unitCost / (1 - rules.marginFloor)) / unitList);

  // Full precision on purpose: rounding the cap up breaches the floor it enforces.
  return requested > ceiling
    ? { discount: ceiling, capped: true, requested: requested }
    : { discount: requested, capped: false, requested: requested };
}

function buildQuote() {
  var book = SpreadsheetApp.getActive();
  var sheet = book.getSheetByName(QUOTE_SHEET);
  var catalog = loadCatalog(book);
  var rules = loadRules(book);
  var tier = String(sheet.getRange('B4').getValue()).trim();

  var input = sheet.getRange(FIRST_LINE, 2, MAX_LINES, 11).getValues(); // B..L
  var output = [];
  var internal = [];
  var subtotal = 0;
  var notes = [];

  for (var index = 0; index < MAX_LINES; index += 1) {
    var row = input[index];
    var code = String(row[0] || '').trim();
    if (!code) {
      output.push(['', '', '', '', '', '', '', '', '']);
      internal.push(['']);
      continue;
    }

    var product = catalog.products[code];
    if (!product) { throw new Error('Unknown product code: ' + code); }

    var quantity = Number(row[5]);
    if (!quantity || quantity < 1 || quantity !== Math.floor(quantity)) {
      throw new Error('Row ' + (FIRST_LINE + index) +
                      ': quantity must be a whole number of 1 or more.');
    }

    var unitList = product.price;
    var unitCost = product.cost;
    var chosen = [row[2], row[3], row[4]];
    for (var slot = 0; slot < chosen.length; slot += 1) {
      var optionCode = String(chosen[slot] || '').trim();
      if (!optionCode) { continue; }
      var option = catalog.options[code + '|' + optionCode];
      if (!option) {
        throw new Error('Option ' + optionCode + ' does not belong to ' + code);
      }
      unitList += option.price;
      unitCost += option.cost;
    }

    var priced = priceLine(rules, unitList, unitCost, quantity, tier, Number(row[10]) || 0);
    var net = roundHalfUp(unitList * (1 - priced.discount), 2);
    var lineTotal = roundHalfUp(net * quantity, 2);
    subtotal += lineTotal;

    if (priced.capped) {
      notes.push('Row ' + (FIRST_LINE + index) + ': discount capped at ' +
                 (priced.discount * 100).toFixed(2) + '% by the margin floor (requested ' +
                 (priced.requested * 100).toFixed(2) + '%).');
    }

    // C description, D-F options untouched, G qty untouched, H-K computed.
    output.push([product.name, row[2], row[3], row[4], quantity,
                 unitList, priced.discount, net, lineTotal]);
    internal.push([unitCost * quantity]);
  }

  sheet.getRange(FIRST_LINE, 3, MAX_LINES, 9).setValues(output);
  sheet.getRange(FIRST_LINE, 13, MAX_LINES, 1).setValues(internal);

  subtotal = roundHalfUp(subtotal, 2);
  var vatAmount = roundHalfUp(subtotal * rules.vat, 2);
  var totalsRow = FIRST_LINE + MAX_LINES + 1;
  sheet.getRange(totalsRow, 11).setValue(subtotal);
  sheet.getRange(totalsRow + 1, 11).setValue(vatAmount);
  sheet.getRange(totalsRow + 2, 11).setValue(roundHalfUp(subtotal + vatAmount, 2));

  var quoteDate = sheet.getRange('B5').getValue();
  if (quoteDate instanceof Date) {
    var until = new Date(quoteDate.getTime());
    until.setDate(until.getDate() + rules.validDays);
    sheet.getRange('B6').setValue(until);
  }

  if (notes.length) {
    SpreadsheetApp.getUi().alert('Quote built.\n\n' + notes.join('\n'));
  }
}

/** Emails the Quote sheet as a PDF to the address in B7. */
function emailQuotePdf() {
  var book = SpreadsheetApp.getActive();
  var sheet = book.getSheetByName(QUOTE_SHEET);
  var recipient = String(sheet.getRange('B7').getValue()).trim();

  if (!recipient) {
    SpreadsheetApp.getUi().alert('Put the recipient email in cell B7 first.');
    return;
  }

  var url = book.getUrl().replace(/edit.*$/, '') +
    'export?format=pdf&gid=' + sheet.getSheetId() +
    '&portrait=true&fitw=true&gridlines=false&range=A1:K30';

  var response = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  });

  if (response.getResponseCode() !== 200) {
    SpreadsheetApp.getUi().alert('Could not export the PDF (HTTP ' +
                                 response.getResponseCode() + ').');
    return;
  }

  var customer = String(sheet.getRange('B3').getValue()).trim() || 'customer';
  var blob = response.getBlob().setName('Quote_' + customer + '.pdf');
  MailApp.sendEmail({
    to: recipient,
    subject: 'Quotation for ' + customer,
    body: 'The quotation is attached. It is valid until ' +
          sheet.getRange('B6').getDisplayValue() + '.',
    attachments: [blob]
  });

  SpreadsheetApp.getUi().alert('Sent to ' + recipient + '.');
}

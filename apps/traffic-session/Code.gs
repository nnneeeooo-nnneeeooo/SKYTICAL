/** SKYTICAL owner-only GA4 session. Google retains and refreshes authorization.
 * Deploy as USER_DEPLOYING, access MYSELF. Never publish to ANYONE/ANONYMOUS.
 * Configure GA4_PROPERTY_ID in Script Properties, not in HTML or a query string.
 */
function doGet() {
  const response = UrlFetchApp.fetch('https://skytical.tech/assets/traffic-dashboard-app.html', {
    followRedirects: false, muteHttpExceptions: true, headers: {'Cache-Control': 'no-cache'}
  });
  const html = response.getContentText();
  if (response.getResponseCode() !== 200 || !html.includes('data-traffic-transport="apps-script"')) {
    throw new Error('儀表板介面暫時無法載入，請稍後重新整理。');
  }
  return HtmlService.createHtmlOutput(html).setTitle('SKYTICAL｜私人流量儀表板')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function runTrafficReport(body) {
  // The deployment is owner-only. No caller-provided property ID, endpoint,
  // OAuth token or arbitrary API method is accepted.
  const property = PropertiesService.getScriptProperties().getProperty('GA4_PROPERTY_ID') || '';
  if (!/^[0-9]{5,20}$/.test(property)) throw new Error('請在指令碼屬性設定 GA4_PROPERTY_ID。');
  validateTrafficRequest_(body);
  return JSON.parse(JSON.stringify(AnalyticsData.Properties.runReport(body, 'properties/' + property)));
}

function validateTrafficRequest_(body) {
  const allowed = new Set(['dateRanges','metrics','dimensions','dimensionFilter','orderBys','limit']);
  if (!body || typeof body !== 'object' || Array.isArray(body) || Object.keys(body).some(k => !allowed.has(k))) throw new Error('不支援的報表要求。');
  const range = body.dateRanges && body.dateRanges[0];
  if (!range || !Array.isArray(body.dateRanges) || body.dateRanges.length !== 1) throw new Error('請提供一組日期。');
  const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0,10) === value;
  if (!validDate(range.startDate) || !validDate(range.endDate)) throw new Error('日期格式不正確。');
  const span = Date.parse(range.endDate) - Date.parse(range.startDate);
  if (span < 0 || span >= 366 * 86400000) throw new Error('每次最多可查看 366 天。');
  const metrics = new Set(['activeUsers','sessions','screenPageViews','engagementRate']);
  const dimensions = new Set(['date','sessionSourceMedium','pagePath']);
  if (!Array.isArray(body.metrics) || !body.metrics.length || body.metrics.length > 4 || body.metrics.some(m => !m || !metrics.has(m.name) || Object.keys(m).length !== 1)) throw new Error('不支援的統計指標。');
  if (body.dimensions && (!Array.isArray(body.dimensions) || body.dimensions.length > 1 || body.dimensions.some(d => !d || !dimensions.has(d.name) || Object.keys(d).length !== 1))) throw new Error('不支援的統計維度。');
  if (body.limit !== undefined && (!Number.isInteger(body.limit) || body.limit < 1 || body.limit > 366)) throw new Error('資料筆數超出限制。');
  if (body.dimensionFilter) {
    const expected = {filter:{fieldName:'sessionSource',stringFilter:{matchType:'PARTIAL_REGEXP',value:'facebook|(^|[.])fb([./]|$)',caseSensitive:false}}};
    if (JSON.stringify(body.dimensionFilter) !== JSON.stringify(expected)) throw new Error('不支援的來源篩選。');
  }
  if (body.orderBys && (!Array.isArray(body.orderBys) || body.orderBys.length > 1 || body.orderBys.some(order => {
    const expected = order.dimension ? {dimension:{dimensionName:'date'}} : {metric:{metricName:body.metrics[0].name},desc:true};
    return JSON.stringify(order) !== JSON.stringify(expected);
  }))) throw new Error('不支援的排序。');
}

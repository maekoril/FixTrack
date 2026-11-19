const day = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const timestamp = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
const utcDay = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeZone: 'UTC' });
const currency = new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP' });

export const formatDate = (value: string) => day.format(new Date(value));
export const formatDateTime = (value: string) => timestamp.format(new Date(value));
export const formatReportDate = (value: string) => utcDay.format(new Date(value));
export const formatMoney = (value: string) => currency.format(Number(value));

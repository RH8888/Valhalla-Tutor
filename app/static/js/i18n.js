/* Valhalla Tutor — Client-Side i18n, Digits, Chart.js RTL & Seamless Language Switching */
(function () {
    const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

    window.vtLocale = function () {
        return document.documentElement.lang === "fa" ? "fa" : "en";
    };

    window.vtIsRtl = function () {
        return document.documentElement.dir === "rtl";
    };

    window.vtDigits = function (val) {
        if (val === null || val === undefined) return "";
        const s = String(val);
        if (!window.vtIsRtl()) return s;
        return s.replace(/[0-9]/g, function (d) {
            return PERSIAN_DIGITS[Number(d)];
        });
    };

    window.vtNumber = function (val, decimals) {
        if (val === null || val === undefined || val === "") return "";
        const num = Number(val);
        if (Number.isNaN(num)) return window.vtDigits(val);
        if (!window.vtIsRtl()) {
            return decimals !== undefined ? num.toFixed(decimals) : String(num);
        }
        try {
            return new Intl.NumberFormat("fa-IR", {
                minimumFractionDigits: decimals !== undefined ? decimals : 0,
                maximumFractionDigits: decimals !== undefined ? decimals : 2,
            }).format(num);
        } catch (_) {
            return window.vtDigits(num);
        }
    };

    window.vtPercent = function (val, decimals) {
        if (val === null || val === undefined || val === "") return "";
        if (!window.vtIsRtl()) {
            return (decimals !== undefined ? Number(val).toFixed(decimals) : val) + "%";
        }
        return window.vtNumber(val, decimals) + "٪";
    };

    window.vt = function (key, vars) {
        const dict = window.VALHALLA_I18N || {};
        let text = Object.prototype.hasOwnProperty.call(dict, key) ? dict[key] : key;
        if (vars && typeof text === "string") {
            Object.keys(vars).forEach(function (k) {
                text = text.replace(new RegExp("\\{" + k + "\\}", "g"), vars[k]);
            });
        }
        return text;
    };

    window.vtChartFont = function () {
        return window.vtIsRtl()
            ? "'Vazirmatn', Tahoma, sans-serif"
            : "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
    };

    window.vtFormatDate = function (isoStr) {
        if (!isoStr) return "";
        if (!window.vtIsRtl()) return isoStr;
        try {
            const d = new Date(isoStr.length === 10 ? isoStr + "T12:00:00" : isoStr);
            if (Number.isNaN(d.getTime())) return window.vtDigits(isoStr);
            return new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
                year: "numeric",
                month: "short",
                day: "numeric",
            }).format(d);
        } catch (_) {
            return window.vtDigits(isoStr);
        }
    };

    window.vtApplyChartDefaults = function (ChartLib) {
        if (!ChartLib || !ChartLib.defaults) return;
        ChartLib.defaults.font.family = window.vtChartFont();
        if (ChartLib.defaults.plugins && ChartLib.defaults.plugins.legend) {
            ChartLib.defaults.plugins.legend.rtl = window.vtIsRtl();
            ChartLib.defaults.plugins.legend.textDirection = window.vtIsRtl() ? "rtl" : "ltr";
        }
        if (ChartLib.defaults.plugins && ChartLib.defaults.plugins.tooltip) {
            ChartLib.defaults.plugins.tooltip.rtl = window.vtIsRtl();
            ChartLib.defaults.plugins.tooltip.textDirection = window.vtIsRtl() ? "rtl" : "ltr";
        }
    };

    window.vtSwitchLanguage = function (lang) {
        const currentUrl = window.location.pathname + window.location.search;
        const url = "/set-language?lang=" + encodeURIComponent(lang) + "&redirect_url=" + encodeURIComponent(currentUrl);
        window.location.assign(url);
    };
})();

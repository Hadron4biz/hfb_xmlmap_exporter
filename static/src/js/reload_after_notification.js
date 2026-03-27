/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { NotificationService } from "@web/core/notifications/notification_service";

patch(NotificationService.prototype, {
    async notify(params) {
        const result = await super.notify(params);
        if (params.exec_reload) {
            // Reload po zamknięciu notyfikacji (timeout lub ręcznie)
            setTimeout(() => {
                window.location.reload();
            }, 100);  // krótka zwłoka
        }
        return result;
    },
});

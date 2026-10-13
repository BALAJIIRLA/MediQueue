

/* =========================================================
   MEDIQUEUE — PREMIUM SCROLL FLOAT EFFECT
   ========================================================= */

(function () {
    "use strict";

    function initializeMediQueueScrollFloat() {

        const selectors = [
            ".card",
            ".dashboard-card",
            ".stat-card",
            ".info-card",
            ".doctor-card",
            ".appointment-card",
            ".queue-card",
            ".profile-card",
            ".form-card",
            ".report-card",
            ".analytics-card",
            ".notification-item",
            ".feature-card",
            ".chart-card"
        ];

        const elements = document.querySelectorAll(
            selectors.join(",")
        );

        if (!elements.length) {
            return;
        }

        elements.forEach(function (element, index) {

            /* Do not interfere with elements that are already
               explicitly hidden or are inside navigation. */

            if (
                element.closest("nav") ||
                element.closest(".topbar") ||
                element.closest("header")
            ) {
                return;
            }

            element.classList.add("mq-scroll-float");

            /*
             * Small stagger effect so multiple cards
             * don't appear at exactly the same moment.
             */
            const delay = Math.min(
                (index % 5) * 70,
                280
            );

            element.style.transitionDelay = delay + "ms";
        });

        if (!("IntersectionObserver" in window)) {

            elements.forEach(function (element) {
                element.classList.add("mq-visible");
            });

            return;
        }

        const observer = new IntersectionObserver(
            function (entries) {

                entries.forEach(function (entry) {

                    if (entry.isIntersecting) {

                        entry.target.classList.add(
                            "mq-visible"
                        );

                        observer.unobserve(
                            entry.target
                        );
                    }

                });

            },
            {
                threshold: 0.10,
                rootMargin: "0px 0px -40px 0px"
            }
        );

        elements.forEach(function (element) {

            if (
                element.closest("nav") ||
                element.closest(".topbar") ||
                element.closest("header")
            ) {
                return;
            }

            observer.observe(element);
        });
    }

    if (
        document.readyState === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            initializeMediQueueScrollFloat
        );
    } else {
        initializeMediQueueScrollFloat();
    }

})();

/* =========================================================
   END PREMIUM SCROLL FLOAT EFFECT
   =========================================================
 */


/* =========================================================
   MEDIQUEUE — GLOBAL FLOATING EXPERIENCE JS
   ========================================================= */

(function () {
    "use strict";

    function setupGlobalFloatingExperience() {

        /*
         * Elements that should appear smoothly while
         * entering the viewport.
         */
        const revealSelectors = [
            ".card",
            ".dashboard-card",
            ".stat-card",
            ".info-card",
            ".doctor-card",
            ".appointment-card",
            ".queue-card",
            ".profile-card",
            ".form-card",
            ".report-card",
            ".analytics-card",
            ".notification-item",
            ".feature-card",
            ".chart-card",

            /*
             * Generic structural sections.
             */
            "main > section",
            "main > article",
            ".section",
            ".content-section",
            ".dashboard-section",
            ".analytics-section",
            ".report-section",
            ".features-section"
        ];

        const allElements = [];

        revealSelectors.forEach(function (selector) {

            document.querySelectorAll(selector)
                .forEach(function (element) {

                    if (!allElements.includes(element)) {
                        allElements.push(element);
                    }

                });

        });

        /*
         * Navigation/header/footer are intentionally excluded.
         * They should remain stable while the page moves.
         */
        const elements = allElements.filter(function (element) {

            return !(
                element.closest("nav") ||
                element.closest(".topbar") ||
                element.closest("header") ||
                element.closest("footer")
            );

        });

        /*
         * Add the global floating class.
         */
        elements.forEach(function (element, index) {

            element.classList.add(
                "mq-global-float"
            );

            /*
             * Stagger the entrance slightly.
             * This creates a premium cascading effect.
             */
            const delay =
                Math.min((index % 6) * 55, 275);

            element.style.transitionDelay =
                delay + "ms";
        });

        /*
         * Tables get their own subtle treatment.
         */
        document.querySelectorAll(
            "table"
        ).forEach(function (table) {

            if (
                table.closest("nav") ||
                table.closest(".topbar") ||
                table.closest("header")
            ) {
                return;
            }

            table.classList.add(
                "mq-floating-table"
            );
        });

        /*
         * Forms get a subtle floating shadow.
         */
        document.querySelectorAll(
            "form"
        ).forEach(function (form) {

            if (
                form.closest("nav") ||
                form.closest(".topbar") ||
                form.closest("header")
            ) {
                return;
            }

            form.classList.add(
                "mq-floating-form"
            );
        });

        /*
         * Buttons receive a small hover lift.
         * We do NOT animate them during scroll.
         */
        document.querySelectorAll(
            "button, .btn, .button, " +
            "input[type='submit'], " +
            "input[type='button']"
        ).forEach(function (button) {

            if (
                button.closest("nav") ||
                button.closest(".topbar") ||
                button.closest("header")
            ) {
                return;
            }

            button.classList.add(
                "mq-floating-button"
            );
        });

        /*
         * Important icons receive a very subtle
         * continuous floating movement.
         */
        document.querySelectorAll(
            ".icon, .card-icon, .stat-icon, " +
            ".feature-icon, .notification-icon"
        ).forEach(function (icon) {

            icon.classList.add(
                "mq-floating-icon"
            );

        });

        /*
         * Queue/token areas receive a gentle breathing
         * effect to make live queue feel active.
         */
        document.querySelectorAll(
            ".token, .token-number, " +
            ".current-token, .queue-token, " +
            ".big-token, .live-indicator"
        ).forEach(function (element) {

            element.classList.add(
                "mq-floating-queue"
            );

        });

        /*
         * Intersection Observer.
         */
        if (
            !("IntersectionObserver" in window)
        ) {

            elements.forEach(function (element) {
                element.classList.add(
                    "mq-global-visible"
                );
            });

            document.querySelectorAll(
                "table, form"
            ).forEach(function (element) {
                element.classList.add(
                    "mq-global-visible"
                );
            });

            return;
        }

        const observer =
            new IntersectionObserver(
                function (entries) {

                    entries.forEach(
                        function (entry) {

                            if (
                                entry.isIntersecting
                            ) {

                                entry.target.classList.add(
                                    "mq-global-visible"
                                );

                                observer.unobserve(
                                    entry.target
                                );
                            }

                        }
                    );

                },
                {
                    threshold: 0.08,
                    rootMargin:
                        "0px 0px -35px 0px"
                }
            );

        elements.forEach(
            function (element) {
                observer.observe(element);
            }
        );

        /*
         * Tables and forms also receive the visible
         * state when they enter the viewport.
         */
        document.querySelectorAll(
            "table, form"
        ).forEach(function (element) {

            observer.observe(element);

        });
    }

    /*
     * Start after the page is ready.
     */
    if (
        document.readyState === "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            setupGlobalFloatingExperience
        );

    } else {

        setupGlobalFloatingExperience();

    }

})();

/* =========================================================
   END GLOBAL FLOATING EXPERIENCE JS
   ========================================================= */


(() => {
  "use strict";

  const scrollButton = document.querySelector("#scrollToTop");
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  if (!scrollButton) {
    return;
  }

  const updateScrollButton = () => {
    scrollButton.classList.toggle("is-visible", window.scrollY > 640);
  };

  scrollButton.addEventListener("click", () => {
    window.scrollTo({
      top: 0,
      behavior: prefersReducedMotion.matches ? "auto" : "smooth",
    });
  });

  window.addEventListener("scroll", updateScrollButton, { passive: true });
  updateScrollButton();
})();

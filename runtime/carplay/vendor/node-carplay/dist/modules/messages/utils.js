export const clamp = (number, min, max) => {
    return Math.max(min, Math.min(number, max));
};
export function getCurrentTimeInMs() {
    return Math.round(Date.now() / 1000);
}
//# sourceMappingURL=utils.js.map
package example.economy;

/**
 * 模拟数据（开源示例，非任何真实项目）：奖励发放方式的能力目录。
 *
 * 用途：作为"能力目录 + 复用推荐"特性的演示 / 解析器测试 fixture。
 * 每个成员 = 一种可配置的奖励发放行为，由配表选择，策划用"描述"提需求
 * （"上线就发" / "升级发"），符合 §6.3 的能力目录适用判据。
 *
 * 结构刻意模仿"枚举值(id, 中文名[, 布尔flag])"的常见形态，
 * 用于验证 Phase 1 源码枚举解析函数。
 */
public enum RewardGrantType {

    NONE(0, "未定义"),

    MAIL_GRANT(1, "邮件发放"),          // 奖励塞进邮件，玩家离线也能领
    DIRECT_GRANT(2, "直接入包"),        // 立即放进背包
    LOGIN_GRANT(3, "登录时发放"),       // 玩家下次上线时发放
    LEVELUP_GRANT(4, "升级时发放", true); // 玩家升级时触发发放（true=事件触发型）

    private final int id;
    private final String nameCn;
    private final boolean eventDriven;

    RewardGrantType(int id, String nameCn) {
        this(id, nameCn, false);
    }

    RewardGrantType(int id, String nameCn, boolean eventDriven) {
        this.id = id;
        this.nameCn = nameCn;
        this.eventDriven = eventDriven;
    }

    public int getId() {
        return id;
    }

    public String getNameCn() {
        return nameCn;
    }

    public boolean isEventDriven() {
        return eventDriven;
    }
}

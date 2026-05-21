bash: warning: setlocale: LC_ALL: cannot change locale (zh_CN.UTF-8)
--
-- PostgreSQL database dump
--

-- Dumped from database version 16.4 (Debian 16.4-1.pgdg110+2)
-- Dumped by pg_dump version 16.4 (Debian 16.4-1.pgdg110+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: persona_feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persona_feedback (
    id integer NOT NULL,
    user_id integer NOT NULL,
    output_id integer NOT NULL,
    reaction character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: persona_feedback_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.persona_feedback_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: persona_feedback_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.persona_feedback_id_seq OWNED BY public.persona_feedback.id;


--
-- Name: persona_outputs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persona_outputs (
    id integer NOT NULL,
    user_id integer NOT NULL,
    scene_type character varying(32) NOT NULL,
    template_id integer NOT NULL,
    text_snapshot text NOT NULL,
    shown_at timestamp with time zone NOT NULL,
    activity_id integer
);


--
-- Name: persona_outputs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.persona_outputs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: persona_outputs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.persona_outputs_id_seq OWNED BY public.persona_outputs.id;


--
-- Name: persona_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persona_templates (
    id integer NOT NULL,
    scene_type character varying(32) NOT NULL,
    segment character varying(32),
    template_text text NOT NULL,
    weight integer DEFAULT 1,
    active boolean DEFAULT true
);


--
-- Name: persona_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.persona_templates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: persona_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.persona_templates_id_seq OWNED BY public.persona_templates.id;


--
-- Name: persona_feedback id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_feedback ALTER COLUMN id SET DEFAULT nextval('public.persona_feedback_id_seq'::regclass);


--
-- Name: persona_outputs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_outputs ALTER COLUMN id SET DEFAULT nextval('public.persona_outputs_id_seq'::regclass);


--
-- Name: persona_templates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_templates ALTER COLUMN id SET DEFAULT nextval('public.persona_templates_id_seq'::regclass);


--
-- Data for Name: persona_feedback; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: persona_outputs; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.persona_outputs VALUES (1, 2, 'pr', 6, '8500km 里这一天。', '2026-05-20 06:07:34.030839+00', 325);
INSERT INTO public.persona_outputs VALUES (2, 2, 'segment_distance', 41, '30km。开了个头。', '2026-05-20 06:07:34.042353+00', 419);
INSERT INTO public.persona_outputs VALUES (3, 2, 'segment_distance', 46, '跑出小区了。', '2026-05-20 06:07:34.047406+00', 418);
INSERT INTO public.persona_outputs VALUES (4, 2, 'segment_distance', 44, '腿明天会替你说话。', '2026-05-20 06:07:34.052063+00', 324);
INSERT INTO public.persona_outputs VALUES (5, 2, 'pr', 7, '心率写错了吧？', '2026-05-20 06:07:34.056982+00', 416);
INSERT INTO public.persona_outputs VALUES (6, 2, 'segment_distance', 47, '第一次出趟远门。', '2026-05-20 06:07:34.061906+00', 323);
INSERT INTO public.persona_outputs VALUES (7, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.067266+00', 322);
INSERT INTO public.persona_outputs VALUES (8, 2, 'pr', 11, '破风手得跟你抄作业。', '2026-05-20 06:07:34.073279+00', 321);
INSERT INTO public.persona_outputs VALUES (9, 2, 'pr', 5, '把自己拉爆了。', '2026-05-20 06:07:34.078178+00', 320);
INSERT INTO public.persona_outputs VALUES (10, 2, 'segment_distance', 43, '腿没废吧。', '2026-05-20 06:07:34.082655+00', 319);
INSERT INTO public.persona_outputs VALUES (11, 2, 'extreme', 84, '顺风全程吗？', '2026-05-20 06:07:34.087541+00', 318);
INSERT INTO public.persona_outputs VALUES (12, 2, 'extreme', 101, '几点到家。', '2026-05-20 06:07:34.093803+00', 317);
INSERT INTO public.persona_outputs VALUES (13, 2, 'extreme', 116, '早饭店都没开。', '2026-05-20 06:07:34.098159+00', 316);
INSERT INTO public.persona_outputs VALUES (14, 2, 'segment_distance', 45, '够换一顿好吃的。', '2026-05-20 06:07:34.103537+00', 315);
INSERT INTO public.persona_outputs VALUES (15, 2, 'segment_distance', 42, '明天大概率酸。', '2026-05-20 06:07:34.108795+00', 314);
INSERT INTO public.persona_outputs VALUES (16, 2, 'segment_distance', 41, '30km。开了个头。', '2026-05-20 06:07:34.114781+00', 313);
INSERT INTO public.persona_outputs VALUES (17, 2, 'extreme', 93, '走路都比这快。', '2026-05-20 06:07:34.121591+00', 311);
INSERT INTO public.persona_outputs VALUES (18, 2, 'segment_distance', 41, '30km。开了个头。', '2026-05-20 06:07:34.127067+00', 310);
INSERT INTO public.persona_outputs VALUES (19, 2, 'segment_distance', 41, '30km。开了个头。', '2026-05-20 06:07:34.132671+00', 309);
INSERT INTO public.persona_outputs VALUES (20, 2, 'segment_distance', 41, '30km。开了个头。', '2026-05-20 06:07:34.137337+00', 414);
INSERT INTO public.persona_outputs VALUES (21, 2, 'extreme', 85, '电摩才能这速度。', '2026-05-20 06:07:34.142142+00', 308);
INSERT INTO public.persona_outputs VALUES (22, 2, 'extreme', 82, '这平均速度，摩托吧？', '2026-05-20 06:07:34.147966+00', 307);
INSERT INTO public.persona_outputs VALUES (23, 2, 'segment_distance', 41, '30km。开了个头。', '2026-05-20 06:07:34.153863+00', 306);
INSERT INTO public.persona_outputs VALUES (24, 2, 'segment_distance', 41, '30km。开了个头。', '2026-05-20 06:07:34.158458+00', 305);
INSERT INTO public.persona_outputs VALUES (25, 2, 'pr', 1, '今天嗑药了？', '2026-05-20 06:07:34.162896+00', 304);
INSERT INTO public.persona_outputs VALUES (26, 2, 'extreme', 103, '明天闹钟还响吗。', '2026-05-20 06:07:34.16769+00', 303);
INSERT INTO public.persona_outputs VALUES (27, 2, 'segment_distance', 18, '新人不该这么猛吧。', '2026-05-20 06:07:34.173736+00', 302);
INSERT INTO public.persona_outputs VALUES (28, 2, 'segment_distance', 25, '40 就 40。', '2026-05-20 06:07:34.180552+00', 301);
INSERT INTO public.persona_outputs VALUES (29, 2, 'segment_distance', 51, '入门毕业证拿了。', '2026-05-20 06:07:34.185307+00', 300);
INSERT INTO public.persona_outputs VALUES (30, 2, 'pr', 12, '腿还能走路吗。', '2026-05-20 06:07:34.190243+00', 299);
INSERT INTO public.persona_outputs VALUES (31, 2, 'segment_distance', 50, '腿不抖就好。', '2026-05-20 06:07:34.200432+00', 298);
INSERT INTO public.persona_outputs VALUES (32, 2, 'segment_distance', 24, '今天 40km。可以的吧。', '2026-05-20 06:07:34.204796+00', 297);
INSERT INTO public.persona_outputs VALUES (33, 2, 'segment_distance', 28, '都在状态里。', '2026-05-20 06:07:34.209745+00', 296);
INSERT INTO public.persona_outputs VALUES (34, 2, 'segment_distance', 48, '100km。稳得很。', '2026-05-20 06:07:34.215042+00', 295);
INSERT INTO public.persona_outputs VALUES (35, 2, 'pr', 9, 'Strava 给你弹横幅了吗？', '2026-05-20 06:07:34.221353+00', 293);
INSERT INTO public.persona_outputs VALUES (36, 2, 'segment_distance', 49, '三位数了。', '2026-05-20 06:07:34.225753+00', 292);
INSERT INTO public.persona_outputs VALUES (37, 2, 'segment_distance', 27, '这周稳定了。', '2026-05-20 06:07:34.231887+00', 290);
INSERT INTO public.persona_outputs VALUES (38, 2, 'pr', 14, '不用看排行了。', '2026-05-20 06:07:34.238171+00', 289);
INSERT INTO public.persona_outputs VALUES (39, 2, 'segment_distance', 52, '比上次远 20 吧。', '2026-05-20 06:07:34.244047+00', 288);
INSERT INTO public.persona_outputs VALUES (40, 2, 'segment_distance', 26, '看来入门完毕。', '2026-05-20 06:07:34.248458+00', 287);
INSERT INTO public.persona_outputs VALUES (41, 2, 'pr', 15, '上次这数据是去年。', '2026-05-20 06:07:34.252579+00', 286);
INSERT INTO public.persona_outputs VALUES (42, 2, 'segment_distance', 24, '今天 40km。可以的吧。', '2026-05-20 06:07:34.256635+00', 285);
INSERT INTO public.persona_outputs VALUES (43, 2, 'segment_distance', 24, '今天 40km。可以的吧。', '2026-05-20 06:07:34.260861+00', 284);
INSERT INTO public.persona_outputs VALUES (44, 2, 'segment_distance', 24, '今天 40km。可以的吧。', '2026-05-20 06:07:34.264913+00', 283);
INSERT INTO public.persona_outputs VALUES (45, 2, 'segment_distance', 24, '今天 40km。可以的吧。', '2026-05-20 06:07:34.269227+00', 282);
INSERT INTO public.persona_outputs VALUES (46, 2, 'extreme', 100, '晚饭都没吃吧。', '2026-05-20 06:07:34.275702+00', 280);
INSERT INTO public.persona_outputs VALUES (47, 2, 'segment_distance', 24, '今天 40km。可以的吧。', '2026-05-20 06:07:34.280005+00', 279);
INSERT INTO public.persona_outputs VALUES (48, 2, 'extreme', 102, '灯没忘开吧。', '2026-05-20 06:07:34.286883+00', 278);
INSERT INTO public.persona_outputs VALUES (49, 2, 'pr', 13, '这赛段是你的了。', '2026-05-20 06:07:34.291176+00', 277);
INSERT INTO public.persona_outputs VALUES (50, 2, 'segment_distance', 24, '今天 40km。可以的吧。', '2026-05-20 06:07:34.295239+00', 276);
INSERT INTO public.persona_outputs VALUES (51, 2, 'extreme', 120, '天亮前先出门。', '2026-05-20 06:07:34.301221+00', 275);
INSERT INTO public.persona_outputs VALUES (52, 2, 'pr', 16, '今年最快这一蹬。', '2026-05-20 06:07:34.305272+00', 273);
INSERT INTO public.persona_outputs VALUES (53, 2, 'pr', 10, '明天还能上车吗。', '2026-05-20 06:07:34.310765+00', 272);
INSERT INTO public.persona_outputs VALUES (54, 2, 'segment_distance', 24, '今天 40km。可以的吧。', '2026-05-20 06:07:34.314988+00', 270);
INSERT INTO public.persona_outputs VALUES (55, 2, 'segment_distance', 48, '100km。稳得很。', '2026-05-20 06:07:34.322541+00', 267);
INSERT INTO public.persona_outputs VALUES (56, 2, 'segment_distance', 48, '100km。稳得很。', '2026-05-20 06:07:34.328274+00', 264);
INSERT INTO public.persona_outputs VALUES (57, 2, 'extreme', 99, '凉风骑得舒服吧。', '2026-05-20 06:07:34.33319+00', 263);
INSERT INTO public.persona_outputs VALUES (58, 2, 'segment_distance', 24, '今天 40km。可以的吧。', '2026-05-20 06:07:34.339811+00', 262);
INSERT INTO public.persona_outputs VALUES (59, 2, 'extreme', 114, '这点出门？老登。', '2026-05-20 06:07:34.345376+00', 402);
INSERT INTO public.persona_outputs VALUES (60, 2, 'segment_distance', 48, '100km。稳得很。', '2026-05-20 06:07:34.353726+00', 260);
INSERT INTO public.persona_outputs VALUES (61, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.360578+00', 398);
INSERT INTO public.persona_outputs VALUES (62, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.364884+00', 255);
INSERT INTO public.persona_outputs VALUES (63, 2, 'segment_distance', 31, '算是热身了。', '2026-05-20 06:07:34.37216+00', 252);
INSERT INTO public.persona_outputs VALUES (64, 2, 'extreme', 117, '比上班还早。', '2026-05-20 06:07:34.378315+00', 251);
INSERT INTO public.persona_outputs VALUES (65, 2, 'extreme', 95, '是骑还是推。', '2026-05-20 06:07:34.384149+00', 247);
INSERT INTO public.persona_outputs VALUES (66, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.391621+00', 241);
INSERT INTO public.persona_outputs VALUES (67, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.396108+00', 240);
INSERT INTO public.persona_outputs VALUES (68, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.402057+00', 239);
INSERT INTO public.persona_outputs VALUES (69, 2, 'extreme', 119, '第一个上车的。', '2026-05-20 06:07:34.406188+00', 238);
INSERT INTO public.persona_outputs VALUES (70, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.414954+00', 236);
INSERT INTO public.persona_outputs VALUES (71, 2, 'segment_distance', 33, '才出门就到了。', '2026-05-20 06:07:34.422312+00', 234);
INSERT INTO public.persona_outputs VALUES (72, 2, 'extreme', 115, '鸡都没叫。', '2026-05-20 06:07:34.433728+00', 225);
INSERT INTO public.persona_outputs VALUES (73, 2, 'segment_distance', 30, '40km，按部就班。', '2026-05-20 06:07:34.438295+00', 222);
INSERT INTO public.persona_outputs VALUES (74, 2, 'segment_distance', 32, '还能再加 20。', '2026-05-20 06:07:34.442736+00', 221);
INSERT INTO public.persona_outputs VALUES (75, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.449661+00', 220);
INSERT INTO public.persona_outputs VALUES (76, 2, 'segment_distance', 59, '回家先喝一升水。', '2026-05-20 06:07:34.456093+00', 216);
INSERT INTO public.persona_outputs VALUES (77, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.461884+00', 214);
INSERT INTO public.persona_outputs VALUES (78, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.468209+00', 210);
INSERT INTO public.persona_outputs VALUES (79, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.47263+00', 204);
INSERT INTO public.persona_outputs VALUES (80, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.478422+00', 203);
INSERT INTO public.persona_outputs VALUES (81, 2, 'extreme', 118, '天还在赶路。', '2026-05-20 06:07:34.482697+00', 202);
INSERT INTO public.persona_outputs VALUES (82, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.48987+00', 201);
INSERT INTO public.persona_outputs VALUES (83, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.495925+00', 199);
INSERT INTO public.persona_outputs VALUES (84, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.502031+00', 198);
INSERT INTO public.persona_outputs VALUES (85, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.506281+00', 197);
INSERT INTO public.persona_outputs VALUES (86, 2, 'extreme', 83, '心率对得上吗？', '2026-05-20 06:07:34.510564+00', 350);
INSERT INTO public.persona_outputs VALUES (87, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.514793+00', 196);
INSERT INTO public.persona_outputs VALUES (88, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.518923+00', 195);
INSERT INTO public.persona_outputs VALUES (89, 2, 'segment_distance', 55, '150 算认真的了。', '2026-05-20 06:07:34.536207+00', 194);
INSERT INTO public.persona_outputs VALUES (90, 2, 'extreme', 114, '这点出门？老登。', '2026-05-20 06:07:34.54258+00', 348);
INSERT INTO public.persona_outputs VALUES (91, 2, 'extreme', 114, '这点出门？老登。', '2026-05-20 06:07:34.550134+00', 192);
INSERT INTO public.persona_outputs VALUES (92, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.557386+00', 188);
INSERT INTO public.persona_outputs VALUES (93, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.563179+00', 186);
INSERT INTO public.persona_outputs VALUES (94, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.56774+00', 183);
INSERT INTO public.persona_outputs VALUES (95, 2, 'extreme', 114, '这点出门？老登。', '2026-05-20 06:07:34.572029+00', 182);
INSERT INTO public.persona_outputs VALUES (96, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.579497+00', 178);
INSERT INTO public.persona_outputs VALUES (97, 2, 'pr', 4, '前 1% 的一天。', '2026-05-20 06:07:34.584409+00', 176);
INSERT INTO public.persona_outputs VALUES (98, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.589205+00', 175);
INSERT INTO public.persona_outputs VALUES (99, 2, 'extreme', 86, '这功率是人类吗？', '2026-05-20 06:07:34.595065+00', 174);
INSERT INTO public.persona_outputs VALUES (100, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.599549+00', 172);
INSERT INTO public.persona_outputs VALUES (101, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.604709+00', 171);
INSERT INTO public.persona_outputs VALUES (102, 2, 'segment_distance', 58, '裤兜补给还剩吗。', '2026-05-20 06:07:34.610338+00', 169);
INSERT INTO public.persona_outputs VALUES (103, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.616142+00', 168);
INSERT INTO public.persona_outputs VALUES (105, 2, 'extreme', 114, '这点出门？老登。', '2026-05-20 06:07:34.627135+00', 166);
INSERT INTO public.persona_outputs VALUES (106, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.632827+00', 164);
INSERT INTO public.persona_outputs VALUES (107, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.639866+00', 163);
INSERT INTO public.persona_outputs VALUES (109, 2, 'pr', 3, '数据有点过分。', '2026-05-20 06:07:34.652788+00', 160);
INSERT INTO public.persona_outputs VALUES (110, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.65693+00', 159);
INSERT INTO public.persona_outputs VALUES (111, 2, 'extreme', 82, '这平均速度，摩托吧？', '2026-05-20 06:07:34.662221+00', 157);
INSERT INTO public.persona_outputs VALUES (112, 2, 'extreme', 82, '这平均速度，摩托吧？', '2026-05-20 06:07:34.666832+00', 156);
INSERT INTO public.persona_outputs VALUES (113, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.676021+00', 152);
INSERT INTO public.persona_outputs VALUES (114, 2, 'pr', 2, '今天你最猛。', '2026-05-20 06:07:34.685292+00', 151);
INSERT INTO public.persona_outputs VALUES (116, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.694229+00', 150);
INSERT INTO public.persona_outputs VALUES (117, 2, 'pr', 8, '功率表准吗？', '2026-05-20 06:07:34.700098+00', 148);
INSERT INTO public.persona_outputs VALUES (118, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.708791+00', 147);
INSERT INTO public.persona_outputs VALUES (119, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.725097+00', 145);
INSERT INTO public.persona_outputs VALUES (121, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.741056+00', 142);
INSERT INTO public.persona_outputs VALUES (122, 2, 'segment_distance', 56, '再往上就拼了。', '2026-05-20 06:07:34.745513+00', 141);
INSERT INTO public.persona_outputs VALUES (123, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.750467+00', 140);
INSERT INTO public.persona_outputs VALUES (124, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.755132+00', 139);
INSERT INTO public.persona_outputs VALUES (125, 2, 'segment_distance', 57, '下车两条腿不一样长。', '2026-05-20 06:07:34.761243+00', 138);
INSERT INTO public.persona_outputs VALUES (126, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.766081+00', 137);
INSERT INTO public.persona_outputs VALUES (127, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.77065+00', 136);
INSERT INTO public.persona_outputs VALUES (128, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.775243+00', 135);
INSERT INTO public.persona_outputs VALUES (129, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.783398+00', 134);
INSERT INTO public.persona_outputs VALUES (130, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.788618+00', 133);
INSERT INTO public.persona_outputs VALUES (131, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.792859+00', 132);
INSERT INTO public.persona_outputs VALUES (132, 2, 'segment_distance', 54, '糖原顶住没。', '2026-05-20 06:07:34.799496+00', 131);
INSERT INTO public.persona_outputs VALUES (133, 2, 'segment_distance', 53, '150km。说明状态在。', '2026-05-20 06:07:34.807241+00', 125);
INSERT INTO public.persona_outputs VALUES (134, 2, 'segment_distance', 53, '150km。说明状态在。', '2026-05-20 06:07:34.812222+00', 124);
INSERT INTO public.persona_outputs VALUES (135, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.820557+00', 121);
INSERT INTO public.persona_outputs VALUES (136, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.826738+00', 119);
INSERT INTO public.persona_outputs VALUES (137, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.832246+00', 117);
INSERT INTO public.persona_outputs VALUES (138, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.837045+00', 115);
INSERT INTO public.persona_outputs VALUES (139, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.843155+00', 113);
INSERT INTO public.persona_outputs VALUES (140, 2, 'extreme', 114, '这点出门？老登。', '2026-05-20 06:07:34.848075+00', 336);
INSERT INTO public.persona_outputs VALUES (141, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.853035+00', 110);
INSERT INTO public.persona_outputs VALUES (142, 2, 'extreme', 94, '城里堵车水平。', '2026-05-20 06:07:34.862165+00', 106);
INSERT INTO public.persona_outputs VALUES (143, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.867215+00', 105);
INSERT INTO public.persona_outputs VALUES (144, 2, 'segment_distance', 53, '150km。说明状态在。', '2026-05-20 06:07:34.877068+00', 99);
INSERT INTO public.persona_outputs VALUES (145, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.881471+00', 98);
INSERT INTO public.persona_outputs VALUES (146, 2, 'extreme', 114, '这点出门？老登。', '2026-05-20 06:07:34.887135+00', 96);
INSERT INTO public.persona_outputs VALUES (147, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.892067+00', 94);
INSERT INTO public.persona_outputs VALUES (148, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.899752+00', 87);
INSERT INTO public.persona_outputs VALUES (149, 2, 'segment_distance', 53, '150km。说明状态在。', '2026-05-20 06:07:34.908935+00', 82);
INSERT INTO public.persona_outputs VALUES (150, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.91409+00', 81);
INSERT INTO public.persona_outputs VALUES (151, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.91848+00', 80);
INSERT INTO public.persona_outputs VALUES (152, 2, 'segment_distance', 40, '半壶水的事儿。', '2026-05-20 06:07:34.922879+00', 79);
INSERT INTO public.persona_outputs VALUES (153, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.927338+00', 78);
INSERT INTO public.persona_outputs VALUES (154, 2, 'extreme', 114, '这点出门？老登。', '2026-05-20 06:07:34.931803+00', 77);
INSERT INTO public.persona_outputs VALUES (155, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:34.936417+00', 76);
INSERT INTO public.persona_outputs VALUES (156, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.945538+00', 69);
INSERT INTO public.persona_outputs VALUES (157, 2, 'segment_distance', 37, '还没出汗呢。', '2026-05-20 06:07:34.955503+00', 66);
INSERT INTO public.persona_outputs VALUES (158, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.961056+00', 65);
INSERT INTO public.persona_outputs VALUES (159, 2, 'segment_distance', 39, '早饭都没消化完。', '2026-05-20 06:07:34.965945+00', 64);
INSERT INTO public.persona_outputs VALUES (160, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.974709+00', 62);
INSERT INTO public.persona_outputs VALUES (161, 2, 'extreme', 97, '今天就佛系。', '2026-05-20 06:07:34.981069+00', 59);
INSERT INTO public.persona_outputs VALUES (162, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:34.987095+00', 56);
INSERT INTO public.persona_outputs VALUES (163, 2, 'segment_distance', 38, '出去吹个风。', '2026-05-20 06:07:34.992143+00', 55);
INSERT INTO public.persona_outputs VALUES (164, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:34.999553+00', 53);
INSERT INTO public.persona_outputs VALUES (165, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:35.005022+00', 50);
INSERT INTO public.persona_outputs VALUES (166, 2, 'segment_distance', 35, '撒个尿就回了。', '2026-05-20 06:07:35.010979+00', 49);
INSERT INTO public.persona_outputs VALUES (108, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.647002+00', NULL);
INSERT INTO public.persona_outputs VALUES (167, 2, 'segment_distance', 34, '40km。蹬两脚意思意思。', '2026-05-20 06:07:35.017647+00', 47);
INSERT INTO public.persona_outputs VALUES (168, 2, 'segment_distance', 36, '40 拉得有点划水。', '2026-05-20 06:07:35.024818+00', 46);
INSERT INTO public.persona_outputs VALUES (169, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:35.030569+00', 32);
INSERT INTO public.persona_outputs VALUES (170, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:35.040923+00', 26);
INSERT INTO public.persona_outputs VALUES (171, 2, 'extreme', 114, '这点出门？老登。', '2026-05-20 06:07:35.046085+00', 25);
INSERT INTO public.persona_outputs VALUES (172, 2, 'extreme', 82, '这平均速度，摩托吧？', '2026-05-20 06:07:35.052143+00', 23);
INSERT INTO public.persona_outputs VALUES (173, 2, 'segment_distance', 34, '40km。蹬两脚意思意思。', '2026-05-20 06:07:35.057161+00', 22);
INSERT INTO public.persona_outputs VALUES (174, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:35.062111+00', 21);
INSERT INTO public.persona_outputs VALUES (175, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:35.067366+00', 15);
INSERT INTO public.persona_outputs VALUES (176, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:35.073175+00', 13);
INSERT INTO public.persona_outputs VALUES (177, 2, 'segment_distance', 34, '40km。蹬两脚意思意思。', '2026-05-20 06:07:35.077706+00', 12);
INSERT INTO public.persona_outputs VALUES (178, 2, 'segment_distance', 34, '40km。蹬两脚意思意思。', '2026-05-20 06:07:35.082482+00', 11);
INSERT INTO public.persona_outputs VALUES (179, 2, 'segment_distance', 34, '40km。蹬两脚意思意思。', '2026-05-20 06:07:35.087069+00', 10);
INSERT INTO public.persona_outputs VALUES (180, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:35.091923+00', 9);
INSERT INTO public.persona_outputs VALUES (181, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:35.100399+00', 6);
INSERT INTO public.persona_outputs VALUES (182, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:35.105238+00', 45);
INSERT INTO public.persona_outputs VALUES (183, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:35.109926+00', 44);
INSERT INTO public.persona_outputs VALUES (184, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:35.114504+00', 43);
INSERT INTO public.persona_outputs VALUES (185, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:35.12428+00', 42);
INSERT INTO public.persona_outputs VALUES (186, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:35.128918+00', 41);
INSERT INTO public.persona_outputs VALUES (187, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:35.133451+00', 40);
INSERT INTO public.persona_outputs VALUES (188, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:35.137865+00', 39);
INSERT INTO public.persona_outputs VALUES (189, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:35.144594+00', 37);
INSERT INTO public.persona_outputs VALUES (190, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:35.149581+00', 36);
INSERT INTO public.persona_outputs VALUES (191, 2, 'extreme', 92, '今天电助力坏了吗？', '2026-05-20 06:07:35.154319+00', 35);
INSERT INTO public.persona_outputs VALUES (192, 2, 'segment_distance', 34, '40km。蹬两脚意思意思。', '2026-05-20 06:07:35.159+00', 327);
INSERT INTO public.persona_outputs VALUES (193, 2, 'segment_distance', 34, '40km。蹬两脚意思意思。', '2026-05-20 06:07:35.163856+00', 422);
INSERT INTO public.persona_outputs VALUES (104, 2, 'segment_distance', 29, '今天 40km。日常水平了。', '2026-05-20 06:07:34.620839+00', NULL);
INSERT INTO public.persona_outputs VALUES (115, 2, 'extreme', 98, '又是夜骑党。', '2026-05-20 06:07:34.689896+00', NULL);
INSERT INTO public.persona_outputs VALUES (120, 2, 'extreme', 96, '车带着你走的吗。', '2026-05-20 06:07:34.730516+00', NULL);


--
-- Data for Name: persona_templates; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.persona_templates VALUES (1, 'pr', NULL, '今天嗑药了？', 1, true);
INSERT INTO public.persona_templates VALUES (2, 'pr', NULL, '今天你最猛。', 1, true);
INSERT INTO public.persona_templates VALUES (3, 'pr', NULL, '数据有点过分。', 1, true);
INSERT INTO public.persona_templates VALUES (4, 'pr', NULL, '前 1% 的一天。', 1, true);
INSERT INTO public.persona_templates VALUES (5, 'pr', NULL, '把自己拉爆了。', 1, true);
INSERT INTO public.persona_templates VALUES (6, 'pr', NULL, '8500km 里这一天。', 1, true);
INSERT INTO public.persona_templates VALUES (7, 'pr', NULL, '心率写错了吧？', 1, true);
INSERT INTO public.persona_templates VALUES (8, 'pr', NULL, '功率表准吗？', 1, true);
INSERT INTO public.persona_templates VALUES (9, 'pr', NULL, 'Strava 给你弹横幅了吗？', 1, true);
INSERT INTO public.persona_templates VALUES (10, 'pr', NULL, '明天还能上车吗。', 1, true);
INSERT INTO public.persona_templates VALUES (11, 'pr', NULL, '破风手得跟你抄作业。', 1, true);
INSERT INTO public.persona_templates VALUES (12, 'pr', NULL, '腿还能走路吗。', 1, true);
INSERT INTO public.persona_templates VALUES (13, 'pr', NULL, '这赛段是你的了。', 1, true);
INSERT INTO public.persona_templates VALUES (14, 'pr', NULL, '不用看排行了。', 1, true);
INSERT INTO public.persona_templates VALUES (15, 'pr', NULL, '上次这数据是去年。', 1, true);
INSERT INTO public.persona_templates VALUES (16, 'pr', NULL, '今年最快这一蹬。', 1, true);
INSERT INTO public.persona_templates VALUES (17, 'segment_distance', 'rookie_normal', '今天 40km。挺猛。', 1, true);
INSERT INTO public.persona_templates VALUES (18, 'segment_distance', 'rookie_normal', '新人不该这么猛吧。', 1, true);
INSERT INTO public.persona_templates VALUES (19, 'segment_distance', 'rookie_normal', '看不出来才骑两月。', 1, true);
INSERT INTO public.persona_templates VALUES (20, 'segment_distance', 'rookie_normal', '萌新打老登卡。', 1, true);
INSERT INTO public.persona_templates VALUES (21, 'segment_distance', 'rookie_normal', '够你说一周。', 1, true);
INSERT INTO public.persona_templates VALUES (22, 'segment_distance', 'rookie_normal', '腿不酸算赢。', 1, true);
INSERT INTO public.persona_templates VALUES (23, 'segment_distance', 'rookie_normal', '好歹是开完了。', 1, true);
INSERT INTO public.persona_templates VALUES (24, 'segment_distance', 'entry_normal', '今天 40km。可以的吧。', 1, true);
INSERT INTO public.persona_templates VALUES (25, 'segment_distance', 'entry_normal', '40 就 40。', 1, true);
INSERT INTO public.persona_templates VALUES (26, 'segment_distance', 'entry_normal', '看来入门完毕。', 1, true);
INSERT INTO public.persona_templates VALUES (27, 'segment_distance', 'entry_normal', '这周稳定了。', 1, true);
INSERT INTO public.persona_templates VALUES (28, 'segment_distance', 'entry_normal', '都在状态里。', 1, true);
INSERT INTO public.persona_templates VALUES (29, 'segment_distance', 'mid_normal', '今天 40km。日常水平了。', 1, true);
INSERT INTO public.persona_templates VALUES (30, 'segment_distance', 'mid_normal', '40km，按部就班。', 1, true);
INSERT INTO public.persona_templates VALUES (31, 'segment_distance', 'mid_normal', '算是热身了。', 1, true);
INSERT INTO public.persona_templates VALUES (32, 'segment_distance', 'mid_normal', '还能再加 20。', 1, true);
INSERT INTO public.persona_templates VALUES (33, 'segment_distance', 'mid_normal', '才出门就到了。', 1, true);
INSERT INTO public.persona_templates VALUES (34, 'segment_distance', 'veteran_normal', '40km。蹬两脚意思意思。', 1, true);
INSERT INTO public.persona_templates VALUES (35, 'segment_distance', 'veteran_normal', '撒个尿就回了。', 1, true);
INSERT INTO public.persona_templates VALUES (36, 'segment_distance', 'veteran_normal', '40 拉得有点划水。', 1, true);
INSERT INTO public.persona_templates VALUES (37, 'segment_distance', 'veteran_normal', '还没出汗呢。', 1, true);
INSERT INTO public.persona_templates VALUES (38, 'segment_distance', 'veteran_normal', '出去吹个风。', 1, true);
INSERT INTO public.persona_templates VALUES (39, 'segment_distance', 'veteran_normal', '早饭都没消化完。', 1, true);
INSERT INTO public.persona_templates VALUES (40, 'segment_distance', 'veteran_normal', '半壶水的事儿。', 1, true);
INSERT INTO public.persona_templates VALUES (41, 'segment_distance', 'rookie_short', '30km。开了个头。', 1, true);
INSERT INTO public.persona_templates VALUES (42, 'segment_distance', 'rookie_short', '明天大概率酸。', 1, true);
INSERT INTO public.persona_templates VALUES (43, 'segment_distance', 'rookie_short', '腿没废吧。', 1, true);
INSERT INTO public.persona_templates VALUES (44, 'segment_distance', 'rookie_short', '腿明天会替你说话。', 1, true);
INSERT INTO public.persona_templates VALUES (45, 'segment_distance', 'rookie_short', '够换一顿好吃的。', 1, true);
INSERT INTO public.persona_templates VALUES (46, 'segment_distance', 'rookie_short', '跑出小区了。', 1, true);
INSERT INTO public.persona_templates VALUES (47, 'segment_distance', 'rookie_short', '第一次出趟远门。', 1, true);
INSERT INTO public.persona_templates VALUES (48, 'segment_distance', 'entry_long', '100km。稳得很。', 1, true);
INSERT INTO public.persona_templates VALUES (49, 'segment_distance', 'entry_long', '三位数了。', 1, true);
INSERT INTO public.persona_templates VALUES (50, 'segment_distance', 'entry_long', '腿不抖就好。', 1, true);
INSERT INTO public.persona_templates VALUES (51, 'segment_distance', 'entry_long', '入门毕业证拿了。', 1, true);
INSERT INTO public.persona_templates VALUES (52, 'segment_distance', 'entry_long', '比上次远 20 吧。', 1, true);
INSERT INTO public.persona_templates VALUES (53, 'segment_distance', 'mid_long', '150km。说明状态在。', 1, true);
INSERT INTO public.persona_templates VALUES (54, 'segment_distance', 'mid_long', '糖原顶住没。', 1, true);
INSERT INTO public.persona_templates VALUES (55, 'segment_distance', 'mid_long', '150 算认真的了。', 1, true);
INSERT INTO public.persona_templates VALUES (56, 'segment_distance', 'mid_long', '再往上就拼了。', 1, true);
INSERT INTO public.persona_templates VALUES (57, 'segment_distance', 'mid_long', '下车两条腿不一样长。', 1, true);
INSERT INTO public.persona_templates VALUES (58, 'segment_distance', 'mid_long', '裤兜补给还剩吗。', 1, true);
INSERT INTO public.persona_templates VALUES (59, 'segment_distance', 'mid_long', '回家先喝一升水。', 1, true);
INSERT INTO public.persona_templates VALUES (60, 'segment_distance', 'veteran_extreme', '200km。膝盖呢。', 1, true);
INSERT INTO public.persona_templates VALUES (61, 'segment_distance', 'veteran_extreme', '第二天能走吗。', 1, true);
INSERT INTO public.persona_templates VALUES (62, 'segment_distance', 'veteran_extreme', '链条都酸了吧。', 1, true);
INSERT INTO public.persona_templates VALUES (63, 'segment_distance', 'veteran_extreme', '路上撒了几次尿。', 1, true);
INSERT INTO public.persona_templates VALUES (64, 'segment_distance', 'veteran_extreme', '腰还连着腿吗。', 1, true);
INSERT INTO public.persona_templates VALUES (65, 'consecutive_high', NULL, '把膝盖磨成粉了？', 1, true);
INSERT INTO public.persona_templates VALUES (66, 'consecutive_high', NULL, '锁鞋焊脚上了？', 1, true);
INSERT INTO public.persona_templates VALUES (67, 'consecutive_high', NULL, '屁股还活着吗？', 1, true);
INSERT INTO public.persona_templates VALUES (68, 'consecutive_high', NULL, '车架冒烟没？', 1, true);
INSERT INTO public.persona_templates VALUES (69, 'consecutive_high', NULL, '本周第 5 次了。', 1, true);
INSERT INTO public.persona_templates VALUES (70, 'consecutive_high', NULL, '今天又上车。停不下来了。', 1, true);
INSERT INTO public.persona_templates VALUES (71, 'silence', NULL, '最近去哪儿了。', 1, true);
INSERT INTO public.persona_templates VALUES (72, 'silence', NULL, '充电桩等你好久了。', 1, true);
INSERT INTO public.persona_templates VALUES (73, 'silence', NULL, '上次骑车 12 天前。', 1, true);
INSERT INTO public.persona_templates VALUES (74, 'silence', NULL, '膝盖恢复完了？', 1, true);
INSERT INTO public.persona_templates VALUES (75, 'silence', NULL, '车蹭灰了吧。', 1, true);
INSERT INTO public.persona_templates VALUES (76, 'silence', NULL, '胎压还在吗。', 1, true);
INSERT INTO public.persona_templates VALUES (77, 'extreme', 'tiny', '5 公里？撒尿都不够。', 1, true);
INSERT INTO public.persona_templates VALUES (78, 'extreme', 'tiny', '等红绿灯都没等够。', 1, true);
INSERT INTO public.persona_templates VALUES (79, 'extreme', 'tiny', 'GPS 都没醒。', 1, true);
INSERT INTO public.persona_templates VALUES (80, 'extreme', 'tiny', '腿都没暖开。', 1, true);
INSERT INTO public.persona_templates VALUES (81, 'extreme', 'tiny', '停车场绕一圈。', 1, true);
INSERT INTO public.persona_templates VALUES (82, 'extreme', 'high_speed', '这平均速度，摩托吧？', 1, true);
INSERT INTO public.persona_templates VALUES (83, 'extreme', 'high_speed', '心率对得上吗？', 1, true);
INSERT INTO public.persona_templates VALUES (84, 'extreme', 'high_speed', '顺风全程吗？', 1, true);
INSERT INTO public.persona_templates VALUES (85, 'extreme', 'high_speed', '电摩才能这速度。', 1, true);
INSERT INTO public.persona_templates VALUES (86, 'extreme', 'high_speed', '这功率是人类吗？', 1, true);
INSERT INTO public.persona_templates VALUES (87, 'extreme', 'late_collapse', '前快后慢，老剧本了。', 1, true);
INSERT INTO public.persona_templates VALUES (88, 'extreme', 'late_collapse', '崩在半路啊。', 1, true);
INSERT INTO public.persona_templates VALUES (89, 'extreme', 'late_collapse', '糖原烧完了吧。', 1, true);
INSERT INTO public.persona_templates VALUES (90, 'extreme', 'late_collapse', '后程像换了人。', 1, true);
INSERT INTO public.persona_templates VALUES (91, 'extreme', 'late_collapse', '节奏没绷住。', 1, true);
INSERT INTO public.persona_templates VALUES (92, 'extreme', 'low_speed', '今天电助力坏了吗？', 1, true);
INSERT INTO public.persona_templates VALUES (93, 'extreme', 'low_speed', '走路都比这快。', 1, true);
INSERT INTO public.persona_templates VALUES (94, 'extreme', 'low_speed', '城里堵车水平。', 1, true);
INSERT INTO public.persona_templates VALUES (95, 'extreme', 'low_speed', '是骑还是推。', 1, true);
INSERT INTO public.persona_templates VALUES (96, 'extreme', 'low_speed', '车带着你走的吗。', 1, true);
INSERT INTO public.persona_templates VALUES (97, 'extreme', 'low_speed', '今天就佛系。', 1, true);
INSERT INTO public.persona_templates VALUES (98, 'extreme', 'night', '又是夜骑党。', 1, true);
INSERT INTO public.persona_templates VALUES (99, 'extreme', 'night', '凉风骑得舒服吧。', 1, true);
INSERT INTO public.persona_templates VALUES (100, 'extreme', 'night', '晚饭都没吃吧。', 1, true);
INSERT INTO public.persona_templates VALUES (101, 'extreme', 'night', '几点到家。', 1, true);
INSERT INTO public.persona_templates VALUES (102, 'extreme', 'night', '灯没忘开吧。', 1, true);
INSERT INTO public.persona_templates VALUES (103, 'extreme', 'night', '明天闹钟还响吗。', 1, true);
INSERT INTO public.persona_templates VALUES (104, 'extreme', 'long_dist', '150km 了。洗澡去吧。', 1, true);
INSERT INTO public.persona_templates VALUES (105, 'extreme', 'long_dist', '明天能坐稳吗。', 1, true);
INSERT INTO public.persona_templates VALUES (106, 'extreme', 'long_dist', '屁股要换皮了。', 1, true);
INSERT INTO public.persona_templates VALUES (107, 'extreme', 'long_dist', '把灯都骑到没电。', 1, true);
INSERT INTO public.persona_templates VALUES (108, 'extreme', 'long_dist', '回家直接平躺。', 1, true);
INSERT INTO public.persona_templates VALUES (109, 'extreme', 'rain', '雨里也出去？禧玛诺交响曲好听吗。', 1, true);
INSERT INTO public.persona_templates VALUES (110, 'extreme', 'rain', '鞋洗了一遍。', 1, true);
INSERT INTO public.persona_templates VALUES (111, 'extreme', 'rain', '今天免费洗车。', 1, true);
INSERT INTO public.persona_templates VALUES (112, 'extreme', 'rain', '雨水比补水多。', 1, true);
INSERT INTO public.persona_templates VALUES (113, 'extreme', 'rain', '刹车快换了吧。', 1, true);
INSERT INTO public.persona_templates VALUES (114, 'extreme', 'early', '这点出门？老登。', 1, true);
INSERT INTO public.persona_templates VALUES (115, 'extreme', 'early', '鸡都没叫。', 1, true);
INSERT INTO public.persona_templates VALUES (116, 'extreme', 'early', '早饭店都没开。', 1, true);
INSERT INTO public.persona_templates VALUES (117, 'extreme', 'early', '比上班还早。', 1, true);
INSERT INTO public.persona_templates VALUES (118, 'extreme', 'early', '天还在赶路。', 1, true);
INSERT INTO public.persona_templates VALUES (119, 'extreme', 'early', '第一个上车的。', 1, true);
INSERT INTO public.persona_templates VALUES (120, 'extreme', 'early', '天亮前先出门。', 1, true);
INSERT INTO public.persona_templates VALUES (121, 'empty_error', 'empty', '还没数据。先去蹬两圈。', 1, true);
INSERT INTO public.persona_templates VALUES (122, 'empty_error', 'empty', '蹬一脚再来看。', 1, true);
INSERT INTO public.persona_templates VALUES (123, 'empty_error', 'empty', '先去刷一圈。', 1, true);
INSERT INTO public.persona_templates VALUES (124, 'empty_error', 'empty', '上路才有数据。', 1, true);
INSERT INTO public.persona_templates VALUES (125, 'empty_error', 'empty', '车在车库吧。', 1, true);
INSERT INTO public.persona_templates VALUES (126, 'empty_error', 'empty', '轨迹还在路上。', 1, true);
INSERT INTO public.persona_templates VALUES (127, 'empty_error', 'empty', '数据等你回家。', 1, true);
INSERT INTO public.persona_templates VALUES (128, 'empty_error', 'upload_failed', '今天轨迹丢了。下次记得开 GPS。', 1, true);
INSERT INTO public.persona_templates VALUES (129, 'empty_error', 'upload_failed', 'GPS 装睡了。', 1, true);
INSERT INTO public.persona_templates VALUES (130, 'empty_error', 'upload_failed', 'GPS 卡壳了。', 1, true);
INSERT INTO public.persona_templates VALUES (131, 'empty_error', 'upload_failed', '数据掉路上了。', 1, true);
INSERT INTO public.persona_templates VALUES (132, 'empty_error', 'upload_failed', '蹬完了没记录。', 1, true);
INSERT INTO public.persona_templates VALUES (133, 'empty_error', 'network_down', '连不上。WiFi 切流量试试。', 1, true);
INSERT INTO public.persona_templates VALUES (134, 'empty_error', 'network_down', '信号在度假。', 1, true);
INSERT INTO public.persona_templates VALUES (135, 'empty_error', 'network_down', 'WiFi 在睡觉。', 1, true);
INSERT INTO public.persona_templates VALUES (136, 'empty_error', 'network_down', '信号比骑友还少。', 1, true);
INSERT INTO public.persona_templates VALUES (137, 'empty_error', 'network_down', '信号 5 分钟前还在。', 1, true);
INSERT INTO public.persona_templates VALUES (138, 'empty_error', 'server_5xx', '服务器在打盹儿。', 1, true);
INSERT INTO public.persona_templates VALUES (139, 'empty_error', 'server_5xx', '后台喘口气。', 1, true);
INSERT INTO public.persona_templates VALUES (140, 'empty_error', 'server_5xx', '后端罢工了。', 1, true);
INSERT INTO public.persona_templates VALUES (141, 'empty_error', 'server_5xx', '服务器去骑车了。', 1, true);
INSERT INTO public.persona_templates VALUES (142, 'empty_error', 'server_5xx', '服务器有点累。', 1, true);
INSERT INTO public.persona_templates VALUES (143, 'empty_error', 'loading', '算你的高光中…', 1, true);
INSERT INTO public.persona_templates VALUES (144, 'empty_error', 'unauth_401', '要重新登录一下了。', 1, true);
INSERT INTO public.persona_templates VALUES (145, 'empty_error', 'unauth_401', '得再敲一次门。', 1, true);
INSERT INTO public.persona_templates VALUES (146, 'empty_error', 'unauth_401', '门没认出你。', 1, true);
INSERT INTO public.persona_templates VALUES (147, 'empty_error', 'unauth_401', '登录卡掉了。', 1, true);
INSERT INTO public.persona_templates VALUES (148, 'empty_error', 'unauth_401', '刷一下重进。', 1, true);
INSERT INTO public.persona_templates VALUES (149, 'surprise', 'solar_term', '立秋了，凉快下来了。', 1, true);
INSERT INTO public.persona_templates VALUES (150, 'surprise', 'solar_term', '霜降了。骑慢点。', 1, true);
INSERT INTO public.persona_templates VALUES (151, 'surprise', 'solar_term', '夏至。白天最长。', 1, true);
INSERT INTO public.persona_templates VALUES (152, 'surprise', 'solar_term', '立冬了。补水改保暖。', 1, true);
INSERT INTO public.persona_templates VALUES (153, 'surprise', 'solar_term', '春分了。该重启了。', 1, true);
INSERT INTO public.persona_templates VALUES (154, 'surprise', 'anniversary', '上车一周年。8500km。', 1, true);
INSERT INTO public.persona_templates VALUES (155, 'surprise', 'anniversary', '365 天没断。', 1, true);
INSERT INTO public.persona_templates VALUES (156, 'surprise', 'anniversary', '一年前你也在路上。', 1, true);
INSERT INTO public.persona_templates VALUES (157, 'surprise', 'anniversary', '去年今天你哪儿？', 1, true);
INSERT INTO public.persona_templates VALUES (158, 'surprise', 'anniversary', '去年的你没想到吧。', 1, true);
INSERT INTO public.persona_templates VALUES (159, 'surprise', 'milestone', '1 万了。老登正式入会。', 1, true);
INSERT INTO public.persona_templates VALUES (160, 'surprise', 'milestone', '破万的人不多。', 1, true);
INSERT INTO public.persona_templates VALUES (161, 'surprise', 'milestone', '10000 公里解锁。', 1, true);
INSERT INTO public.persona_templates VALUES (162, 'surprise', 'milestone', '新里程碑亮了。', 1, true);
INSERT INTO public.persona_templates VALUES (163, 'surprise', 'milestone', '下一站 5 万。', 1, true);
INSERT INTO public.persona_templates VALUES (164, 'surprise', 'new_year', '新年第一蹬。', 1, true);
INSERT INTO public.persona_templates VALUES (165, 'surprise', 'new_year', '去年的腿带到今年。', 1, true);
INSERT INTO public.persona_templates VALUES (166, 'surprise', 'new_year', '新年第一脚。', 1, true);
INSERT INTO public.persona_templates VALUES (167, 'surprise', 'new_year', '第一天先蹬出去。', 1, true);
INSERT INTO public.persona_templates VALUES (168, 'surprise', 'new_year', '跨年骑党到了。', 1, true);


--
-- Name: persona_feedback_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.persona_feedback_id_seq', 1, false);


--
-- Name: persona_outputs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.persona_outputs_id_seq', 193, true);


--
-- Name: persona_templates_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.persona_templates_id_seq', 168, true);


--
-- Name: persona_feedback persona_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_feedback
    ADD CONSTRAINT persona_feedback_pkey PRIMARY KEY (id);


--
-- Name: persona_outputs persona_outputs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_outputs
    ADD CONSTRAINT persona_outputs_pkey PRIMARY KEY (id);


--
-- Name: persona_templates persona_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_templates
    ADD CONSTRAINT persona_templates_pkey PRIMARY KEY (id);


--
-- Name: ix_persona_outputs_user_scene_shown; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_persona_outputs_user_scene_shown ON public.persona_outputs USING btree (user_id, scene_type, shown_at);


--
-- Name: ix_persona_templates_scene_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_persona_templates_scene_active ON public.persona_templates USING btree (scene_type, active);


--
-- Name: persona_feedback persona_feedback_output_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_feedback
    ADD CONSTRAINT persona_feedback_output_id_fkey FOREIGN KEY (output_id) REFERENCES public.persona_outputs(id);


--
-- Name: persona_feedback persona_feedback_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_feedback
    ADD CONSTRAINT persona_feedback_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: persona_outputs persona_outputs_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_outputs
    ADD CONSTRAINT persona_outputs_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id) ON DELETE SET NULL;


--
-- Name: persona_outputs persona_outputs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_outputs
    ADD CONSTRAINT persona_outputs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--


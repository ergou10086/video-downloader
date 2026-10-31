"""Small protocol adapter based on the verified 5.1.1 and live response shapes."""
from __future__ import annotations

from typing import Protocol
from urllib.parse import parse_qs, urlencode, urlsplit

from .errors import FanboxError
from .parsers import require_post
from .urls import validate_api_url


class JsonTransport(Protocol):
    def get_json(self, url: str) -> dict: ...


class FanboxClient:
    def __init__(self, transport: JsonTransport):
        self.transport = transport

    def _get(self, endpoint, **params):
        return self.transport.get_json("https://api.fanbox.cc/" + endpoint + "?" + urlencode(params))["body"]

    def creator(self, creator_id):
        data = self._get("creator.get", creatorId=creator_id)
        if not isinstance(data, dict) or data.get("creatorId") != creator_id or not isinstance(data.get("user"), dict):
            raise FanboxError("schema_changed", "创作者资料响应结构变化")
        return data

    def supporting_creators(self):
        data=self._get('plan.listSupporting')
        plans=data.get('plans') if isinstance(data,dict) else None
        if not isinstance(plans,list) or len(plans)>10000:
            raise FanboxError('schema_changed','赞助列表响应结构变化')
        from .urls import parse_source
        creators=[]
        for plan in plans:
            if not isinstance(plan,dict) or not isinstance(plan.get('creatorId'),str):
                raise FanboxError('schema_changed','赞助列表字段结构变化')
            creators.append(parse_source('https://www.fanbox.cc/@'+plan['creatorId']).creator_id)
        return list(dict.fromkeys(creators))

    def fan_card(self,creator_id,*,show_username=True):
        data=self._get('legacy/support/creator',creatorId=creator_id)
        try:
            plan=data['plan']
            if plan['creatorId']!=creator_id:raise ValueError
            transactions=data.get('supportTransactions',[])
            own_name=(transactions[0]['supporter']['name'] if transactions else '') if show_username else ''
            card={'creator_id':creator_id,'creator_name':plan['user']['name'],'title':plan['title'],
                  'fee':plan['fee'],'since':data['supportStartDatetime'],'username':own_name,
                  'background':plan.get('coverImageUrl') or data.get('supporterCardImageUrl')}
            if (any(not isinstance(card[k],str) or len(card[k])>2000 for k in
                    ('creator_name','title','since','username')) or type(card['fee']) is not int or card['fee']<0):raise ValueError
            if card['background'] is not None:
                from .urls import validate_resource_url
                validate_resource_url(card['background'])
            return card
        except (KeyError,TypeError,ValueError,IndexError):
            raise FanboxError('schema_changed','粉丝卡响应结构变化') from None

    def pages(self, creator_id):
        data = self._get("post.paginateCreator", creatorId=creator_id)
        pages = data.get("pageUrls") if isinstance(data, dict) else data
        if not isinstance(pages, list) or any(not isinstance(url, str) for url in pages):
            raise FanboxError("schema_changed", "创作者分页响应结构变化")
        # Validate all page URLs before fetching even the first page.
        return list(dict.fromkeys(self.page_url(url, creator_id) for url in pages))

    @staticmethod
    def page_url(url, creator_id):
        url = validate_api_url(url, endpoints={"post.listCreator"})
        query = parse_qs(urlsplit(url).query)
        if query.get("creatorId") != [creator_id]:
            raise FanboxError("unsafe_api_url", "分页链接与当前创作者不匹配")
        return url

    def page(self, url, creator_id):
        data = self.transport.get_json(self.page_url(url, creator_id))["body"]
        posts = data.get("posts") if isinstance(data, dict) else data
        if not isinstance(posts, list):
            raise FanboxError("schema_changed", "帖子列表响应结构变化")
        for post in posts:
            require_post(post, detail=False)
            if post["creatorId"] != creator_id:
                raise FanboxError("schema_changed", "帖子列表包含不同创作者")
        return posts

    def post(self, post_id, creator_id):
        data = self._get("post.info", postId=post_id)
        post = data.get("post", data) if isinstance(data, dict) else data
        require_post(post)
        if post["id"] != post_id or post["creatorId"] != creator_id:
            raise FanboxError("schema_changed", "投稿详情与请求标识不匹配")
        return post

    def comments(self, post_id, max_pages=20):
        url = "https://api.fanbox.cc/post.getComments?" + urlencode({"postId":post_id,"offset":0,"limit":50})
        seen_urls, seen_ids, items = set(), set(), []
        offset = 0
        for page in range(max_pages):
            url = validate_api_url(url, endpoints={"post.getComments"})
            if parse_qs(urlsplit(url).query).get("postId") != [post_id]:
                raise FanboxError("unsafe_api_url", "评论分页与投稿不匹配")
            if url in seen_urls:
                return items, False, "comment_pagination_cycle"
            seen_urls.add(url)
            try:
                body = self.transport.get_json(url)["body"]
                data = body["commentList"]
                batch = data["items"]
                if not isinstance(batch, list) or "nextUrl" not in data:
                    raise KeyError
            except FanboxError as error:
                if error.code in {"cancelled", "rate_limited", "challenge_required"}: raise
                return items, False, error.code
            except (KeyError, TypeError):
                raise FanboxError("schema_changed", "评论响应结构变化") from None
            before = len(items)
            for item in batch:
                if not isinstance(item, dict) or not isinstance(item.get("id"), (str, int)):
                    raise FanboxError("schema_changed", "评论字段结构变化")
                identity = str(item["id"])
                if identity not in seen_ids:
                    seen_ids.add(identity);items.append(item)
            offset += len(batch)
            next_url = data["nextUrl"]
            if next_url is not None and not isinstance(next_url, str):
                raise FanboxError("schema_changed", "评论分页地址结构变化")
            if next_url:
                url = next_url
            elif len(batch) >= 50:
                url = "https://api.fanbox.cc/post.getComments?" + urlencode({"postId":post_id,"offset":offset,"limit":50})
            else:
                return items, True, None
            if len(items) == before:
                return items, False, "comment_pagination_cycle"
        return items, False, "comment_page_limit"
